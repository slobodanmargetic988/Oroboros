from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
WORKER_ROOT = WORKSPACE_ROOT / "worker"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models import Run, RunEvent, SlotLease
from worker import orchestrator as worker_orchestrator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClaimPathLeaseVisibilityRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        with self.session_factory() as db:
            run = Run(
                title="Regression run",
                prompt="Implement worker fix",
                status="queued",
                route="/codex",
            )
            db.add(run)
            db.commit()
            self.run_id = run.id

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_claim_path_flush_makes_new_lease_visible_for_assign_worktree(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        def fake_acquire_slot_lease(*, db, run_id: str):
            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            now = _utcnow()
            db.add(
                SlotLease(
                    slot_id="preview-1",
                    run_id=run_id,
                    lease_state="leased",
                    leased_at=now,
                    expires_at=now + timedelta(minutes=5),
                    heartbeat_at=now,
                )
            )
            run.slot_id = "preview-1"
            return {
                "acquired": True,
                "slot_id": "preview-1",
                "queue_reason": None,
                "expires_at": now + timedelta(minutes=5),
                "ttl_seconds": 300,
            }

        def fake_assign_worktree(*, db, run_id: str, slot_id: str):
            lease = (
                db.query(SlotLease)
                .filter(
                    SlotLease.slot_id == slot_id,
                    SlotLease.run_id == run_id,
                    SlotLease.lease_state == "leased",
                )
                .first()
            )
            if lease is None:
                raise ValueError("active_lease_required")

            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            worktree_path = str(Path(temp_dir.name) / slot_id)
            run.worktree_path = worktree_path
            run.branch_name = f"codex/run-{run_id}"
            return {
                "assigned": True,
                "reused": False,
                "slot_id": slot_id,
                "run_id": run_id,
                "branch_name": run.branch_name,
                "worktree_path": worktree_path,
            }

        with (
            patch.object(worker_orchestrator, "SessionLocal", self.session_factory),
            patch.object(worker_orchestrator, "acquire_slot_lease", side_effect=fake_acquire_slot_lease),
            patch.object(worker_orchestrator, "assign_worktree", side_effect=fake_assign_worktree),
            patch.object(worker_orchestrator.WorkerOrchestrator, "_execute_claimed_run") as execute_mock,
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)
        execute_mock.assert_called_once()

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "planning")
            self.assertEqual(run.slot_id, "preview-1")
            self.assertTrue(run.worktree_path)

            events = db.query(RunEvent).filter(RunEvent.run_id == self.run_id).all()
            self.assertTrue(any(event.status_to == "planning" for event in events))


if __name__ == "__main__":
    unittest.main()
