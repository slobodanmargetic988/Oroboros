from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models import Run, RunEvent, SlotLease
from app.services.slot_lease_manager import acquire_slot_lease, reap_expired_slot_leases


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlotLeaseExpiryLinkingTests(unittest.TestCase):
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
                title="slot lease test",
                prompt="slot lease test",
                status=status,
                route="/codex",
                slot_id=slot_id,
            )
            db.add(run)
            db.commit()
            return run.id

    def _create_lease(self, *, slot_id: str, run_id: str, expires_at: datetime) -> None:
        with self.session_factory() as db:
            db.add(
                SlotLease(
                    slot_id=slot_id,
                    run_id=run_id,
                    lease_state="leased",
                    leased_at=expires_at - timedelta(minutes=10),
                    expires_at=expires_at,
                    heartbeat_at=expires_at - timedelta(minutes=1),
                )
            )
            db.commit()

    def test_acquire_reaps_expired_slot_and_marks_previous_run_expired(self) -> None:
        old_run_id = self._create_run(status="editing", slot_id="preview-1")
        self._create_lease(slot_id="preview-1", run_id=old_run_id, expires_at=_utcnow() - timedelta(minutes=2))
        new_run_id = self._create_run(status="queued", slot_id=None)

        with self.session_factory() as db:
            result = acquire_slot_lease(db=db, run_id=new_run_id)
            db.commit()
            self.assertTrue(result["acquired"])
            self.assertEqual(result["slot_id"], "preview-1")

            old_run = db.query(Run).filter(Run.id == old_run_id).first()
            self.assertIsNotNone(old_run)
            self.assertEqual(old_run.status, "expired")
            self.assertIsNone(old_run.slot_id)

            transition_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == old_run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "expired",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(transition_event)
            self.assertEqual(transition_event.payload.get("reason"), "PREVIEW_EXPIRED")
            self.assertEqual(transition_event.payload.get("failure_reason_code"), "PREVIEW_EXPIRED")
            self.assertTrue(transition_event.payload.get("recoverable"))
            self.assertEqual(transition_event.payload.get("resume_endpoint"), f"/api/runs/{old_run_id}/resume")

    def test_reap_expired_slot_leases_marks_run_expired_with_recovery_metadata(self) -> None:
        run_id = self._create_run(status="preview_ready", slot_id="preview-2")
        self._create_lease(slot_id="preview-2", run_id=run_id, expires_at=_utcnow() - timedelta(seconds=5))

        with self.session_factory() as db:
            result = reap_expired_slot_leases(db=db)
            db.commit()

            self.assertEqual(result["expired_count"], 1)
            self.assertEqual(result["expired_slots"], ["preview-2"])

            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "expired")
            self.assertIsNone(run.slot_id)

            transition_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "expired",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(transition_event)
            self.assertEqual(transition_event.payload.get("reason"), "PREVIEW_EXPIRED")
            self.assertEqual(transition_event.payload.get("source"), "slot_reaper")


if __name__ == "__main__":
    unittest.main()
