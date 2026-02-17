from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.api.runs import ExpireRunRequest, cancel_run, expire_run, resume_run, retry_run
from app.db.base import Base
from app.models import Run, RunContext, RunEvent


class RunResilienceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_run(self, *, status: str, slot_id: str | None = None) -> str:
        with self.session_factory() as db:
            run = Run(
                title="Resilience run",
                prompt="resilience",
                status=status,
                route="/codex",
                slot_id=slot_id,
                branch_name=f"codex/run-{status}",
                worktree_path=f"/tmp/{status}",
            )
            db.add(run)
            db.flush()
            db.add(
                RunContext(
                    run_id=run.id,
                    route="/codex",
                    page_title="Codex",
                    note="resilience test",
                    metadata_json={"source": "tests"},
                )
            )
            db.commit()
            return run.id

    def test_cancel_transitions_and_releases_resources(self) -> None:
        run_id = self._create_run(status="editing", slot_id="preview-1")
        with self.session_factory() as db, patch(
            "app.api.runs.cleanup_worktree",
            return_value={"cleaned": True, "slot_id": "preview-1", "run_id": run_id, "reason": None},
        ) as cleanup_mock, patch(
            "app.api.runs.release_slot_lease",
            return_value={"released": True, "slot_id": "preview-1", "run_id": run_id, "reason": None},
        ) as release_mock, patch(
            "app.api.runs.delete_run_branch",
            return_value={"deleted": True, "run_id": run_id, "branch_name": "codex/run-editing", "reason": None},
        ) as delete_branch_mock:
            response = cancel_run(run_id, db)

            self.assertEqual(response.status, "canceled")
            cleanup_mock.assert_called_once_with(db=db, slot_id="preview-1", run_id=run_id)
            release_mock.assert_called_once_with(db=db, slot_id="preview-1", run_id=run_id)
            delete_branch_mock.assert_called_once_with(db=db, run_id=run_id, actor_id=None)

            event = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == run_id, RunEvent.event_type == "status_transition", RunEvent.status_to == "canceled")
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(event)
            self.assertEqual(event.payload.get("source"), "cancel_endpoint")
            self.assertTrue(event.payload.get("resource_cleanup", {}).get("cleaned"))
            self.assertTrue(event.payload.get("lease_release", {}).get("released"))

    def test_retry_creates_linked_child_run(self) -> None:
        run_id = self._create_run(status="failed")
        with self.session_factory() as db:
            response = retry_run(run_id, db)
            self.assertEqual(response.status, "queued")
            self.assertEqual(response.parent_run_id, run_id)

            retried_event = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == response.id, RunEvent.event_type == "run_retried")
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(retried_event)
            self.assertEqual(retried_event.payload.get("parent_run_id"), run_id)

    def test_expire_records_preview_expired_recoverable_metadata(self) -> None:
        run_id = self._create_run(status="preview_ready", slot_id="preview-1")
        with self.session_factory() as db, patch(
            "app.api.runs.cleanup_worktree",
            return_value={"cleaned": True, "slot_id": "preview-1", "run_id": run_id, "reason": None},
        ) as cleanup_mock, patch(
            "app.api.runs.release_slot_lease",
            return_value={"released": True, "slot_id": "preview-1", "run_id": run_id, "reason": None},
        ) as release_mock:
            response = expire_run(run_id, ExpireRunRequest(reason="manual"), db)
            self.assertEqual(response.status, "expired")
            cleanup_mock.assert_called_once_with(db=db, slot_id="preview-1", run_id=run_id)
            release_mock.assert_called_once_with(db=db, slot_id="preview-1", run_id=run_id)

            event = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == run_id, RunEvent.event_type == "status_transition", RunEvent.status_to == "expired")
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(event)
            self.assertEqual(event.payload.get("reason"), "PREVIEW_EXPIRED")
            self.assertEqual(event.payload.get("failure_reason_code"), "PREVIEW_EXPIRED")
            self.assertTrue(event.payload.get("recoverable"))
            self.assertEqual(event.payload.get("resume_endpoint"), f"/api/runs/{run_id}/resume")

    def test_resume_creates_child_for_timeout_failures(self) -> None:
        run_id = self._create_run(status="failed")
        with self.session_factory() as db:
            db.add(
                RunEvent(
                    run_id=run_id,
                    event_type="status_transition",
                    status_from="testing",
                    status_to="failed",
                    payload={"failure_reason_code": "AGENT_TIMEOUT"},
                )
            )
            db.commit()

            response = resume_run(run_id, db)
            self.assertEqual(response.status, "queued")
            self.assertEqual(response.parent_run_id, run_id)

            resumed_event = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == response.id, RunEvent.event_type == "run_resumed")
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(resumed_event)
            self.assertEqual(resumed_event.payload.get("recovery_reason_code"), "AGENT_TIMEOUT")

    def test_resume_rejects_nonrecoverable_failure(self) -> None:
        run_id = self._create_run(status="failed")
        with self.session_factory() as db:
            db.add(
                RunEvent(
                    run_id=run_id,
                    event_type="status_transition",
                    status_from="testing",
                    status_to="failed",
                    payload={"failure_reason_code": "CHECKS_FAILED"},
                )
            )
            db.commit()

            with self.assertRaises(HTTPException) as exc_info:
                resume_run(run_id, db)
            self.assertEqual(exc_info.exception.status_code, 409)
            self.assertIn("resume_not_supported_for_reason", exc_info.exception.detail)


if __name__ == "__main__":
    unittest.main()
