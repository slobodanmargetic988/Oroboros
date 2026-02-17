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
from app.models import AuditLog, Run, RunArtifact, RunEvent, SlotLease, ValidationCheck
from worker import orchestrator as worker_orchestrator
from worker.codex_runner import CommandExecutionResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidationPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        with self.session_factory() as db:
            run = Run(
                title="Validation pipeline run",
                prompt="Implement feature",
                status="queued",
                route="/codex",
            )
            db.add(run)
            db.commit()
            self.run_id = run.id

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _fake_acquire_slot_lease(self, *, db, run_id: str):
        run = db.query(Run).filter(Run.id == run_id).first()
        self.assertIsNotNone(run)
        now = _utcnow()
        db.add(
            SlotLease(
                slot_id="preview-1",
                run_id=run_id,
                lease_state="leased",
                leased_at=now,
                expires_at=now + timedelta(minutes=15),
                heartbeat_at=now,
            )
        )
        run.slot_id = "preview-1"
        return {
            "acquired": True,
            "slot_id": "preview-1",
            "queue_reason": None,
            "expires_at": now + timedelta(minutes=15),
            "ttl_seconds": 900,
        }

    def _fake_assign_worktree(self, *, db, run_id: str, slot_id: str):
        run = db.query(Run).filter(Run.id == run_id).first()
        self.assertIsNotNone(run)
        worktree_path = str(Path(tempfile.gettempdir()) / "oroboros-test-worktree" / slot_id)
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

    def _make_fake_runner(self, plans: list[dict[str, object]]):
        calls = {"count": 0}

        def fake_run_codex_command(**kwargs):
            index = calls["count"]
            calls["count"] += 1
            plan = plans[index]
            output_path: Path = kwargs["output_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(f"step-{index}", encoding="utf-8")
            return CommandExecutionResult(
                exit_code=int(plan.get("exit_code", 0)),
                timed_out=bool(plan.get("timed_out", False)),
                canceled=bool(plan.get("canceled", False)),
                lease_expired=bool(plan.get("lease_expired", False)),
                duration_seconds=0.05,
                output_path=output_path,
                output_excerpt=[f"step-{index}"],
            )

        return fake_run_codex_command

    def test_pipeline_executes_required_checks_and_reaches_preview_ready(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint,test",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            return_value={"slot_id": "preview1", "db_name": "app_preview_1"},
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command", side_effect=self._make_fake_runner(
                [
                    {"exit_code": 0},  # codex command
                    {"exit_code": 0},  # lint
                    {"exit_code": 0},  # test
                ]
            )
        ), patch.object(worker_orchestrator, "build_codex_command", return_value=["codex", "run"]), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_commit_run_worktree_changes",
            return_value=worker_orchestrator.AutoCommitResult(
                committed=True,
                commit_sha="deadbeef",
                changed_file_count=2,
                reason="committed",
            ),
        ), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_publish_preview_surface",
            return_value=worker_orchestrator.PreviewPublishResult(
                published=True,
                web_root_path="/tmp/web-preview-1",
                dist_path="/tmp/worktree/frontend/dist",
                log_artifact_uri="/tmp/preview.publish.log",
                file_count=42,
                error=None,
            ),
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "preview_ready")
            self.assertEqual(run.commit_sha, "deadbeef")

            checks = (
                db.query(ValidationCheck)
                .filter(ValidationCheck.run_id == self.run_id)
                .order_by(ValidationCheck.id.asc())
                .all()
            )
            self.assertEqual([item.check_name for item in checks], ["codex_cli_execution", "lint", "test"])
            self.assertTrue(all(item.status == "passed" for item in checks))
            self.assertTrue(all(item.artifact_uri for item in checks))

            artifacts = (
                db.query(RunArtifact)
                .filter(RunArtifact.run_id == self.run_id)
                .order_by(RunArtifact.id.asc())
                .all()
            )
            self.assertTrue(any(item.artifact_type == "codex_stdout" for item in artifacts))
            self.assertTrue(any(item.artifact_type == "validation_check_log" for item in artifacts))

            audit_actions = [item.action for item in db.query(AuditLog).order_by(AuditLog.id.asc()).all()]
            self.assertIn("run.edit.started", audit_actions)
            self.assertIn("run.edit.completed", audit_actions)
            self.assertIn("run.test.started", audit_actions)
            self.assertIn("run.test.check_completed", audit_actions)
            self.assertIn("run.test.completed", audit_actions)
            self.assertIn("run.edit.commit_created", audit_actions)

    def test_detected_changes_without_commit_marks_run_failed(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            return_value={"slot_id": "preview1", "db_name": "app_preview_1"},
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command", side_effect=self._make_fake_runner([{"exit_code": 0}])
        ), patch.object(
            worker_orchestrator, "build_codex_command", return_value=["codex", "run"]
        ), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_commit_run_worktree_changes",
            return_value=worker_orchestrator.AutoCommitResult(
                committed=False,
                commit_sha="deadbeef",
                changed_file_count=2,
                reason="no_changes",
            ),
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")

            failed_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == self.run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "failed",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(failed_event)
            self.assertEqual(failed_event.payload.get("failure_reason_code"), "UNKNOWN_ERROR")
            self.assertEqual(
                failed_event.payload.get("commit_error"),
                "commit_required_for_detected_changes",
            )

    def test_preview_publish_failure_marks_run_failed(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint,test",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            return_value={"slot_id": "preview1", "db_name": "app_preview_1"},
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command", side_effect=self._make_fake_runner(
                [
                    {"exit_code": 0},  # codex command
                    {"exit_code": 0},  # lint
                    {"exit_code": 0},  # test
                ]
            )
        ), patch.object(
            worker_orchestrator, "build_codex_command", return_value=["codex", "run"]
        ), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_commit_run_worktree_changes",
            return_value=worker_orchestrator.AutoCommitResult(
                committed=True,
                commit_sha="deadbeef",
                changed_file_count=1,
                reason="committed",
            ),
        ), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_publish_preview_surface",
            return_value=worker_orchestrator.PreviewPublishResult(
                published=False,
                web_root_path="/tmp/web-preview-1",
                dist_path="/tmp/worktree/frontend/dist",
                log_artifact_uri="/tmp/preview.publish.log",
                file_count=0,
                error="preview_publish_command_failed:npm run build:exit_1",
            ),
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")

            failed_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == self.run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "failed",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(failed_event)
            self.assertEqual(failed_event.payload.get("failure_reason_code"), "PREVIEW_PUBLISH_FAILED")
            self.assertEqual(
                failed_event.payload.get("preview_publish_error"),
                "preview_publish_command_failed:npm run build:exit_1",
            )

    def test_failed_required_check_marks_run_failed_and_stops_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint,test,smoke",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            return_value={"slot_id": "preview1", "db_name": "app_preview_1"},
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command", side_effect=self._make_fake_runner(
                [
                    {"exit_code": 0},  # codex command
                    {"exit_code": 1},  # lint fails
                ]
            )
        ), patch.object(worker_orchestrator, "build_codex_command", return_value=["codex", "run"]), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_commit_run_worktree_changes",
            return_value=worker_orchestrator.AutoCommitResult(
                committed=True,
                commit_sha="deadbeef",
                changed_file_count=1,
                reason="committed",
            ),
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")

            checks = (
                db.query(ValidationCheck)
                .filter(ValidationCheck.run_id == self.run_id)
                .order_by(ValidationCheck.id.asc())
                .all()
            )
            self.assertEqual([item.check_name for item in checks], ["codex_cli_execution", "lint"])
            self.assertEqual(checks[-1].status, "failed")

            transitions = (
                db.query(RunEvent)
                .filter(RunEvent.run_id == self.run_id, RunEvent.event_type == "status_transition")
                .order_by(RunEvent.id.asc())
                .all()
            )
            self.assertTrue(any(item.status_to == "failed" for item in transitions))
            failed_event = next(item for item in transitions if item.status_to == "failed")
            self.assertEqual(failed_event.payload.get("failure_reason_code"), "CHECKS_FAILED")
            self.assertEqual(failed_event.payload.get("failed_check"), "lint")

    def test_timeout_failure_includes_resume_recovery_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            return_value={"slot_id": "preview1", "db_name": "app_preview_1"},
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command", side_effect=self._make_fake_runner([{"timed_out": True}])
        ), patch.object(worker_orchestrator, "build_codex_command", return_value=["codex", "run"]), patch.object(
            worker_orchestrator.WorkerOrchestrator,
            "_commit_run_worktree_changes",
            return_value=worker_orchestrator.AutoCommitResult(
                committed=False,
                commit_sha="deadbeef",
                changed_file_count=0,
                reason="no_changes",
            ),
        ):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")

            failed_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == self.run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "failed",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(failed_event)
            self.assertEqual(failed_event.payload.get("failure_reason_code"), "AGENT_TIMEOUT")
            self.assertTrue(failed_event.payload.get("recoverable"))
            self.assertEqual(failed_event.payload.get("recovery_strategy"), "create_child_run")
            self.assertEqual(failed_event.payload.get("resume_endpoint"), f"/api/runs/{self.run_id}/resume")

    def test_preview_db_reset_failure_marks_run_failed_and_releases_slot(self) -> None:
        with tempfile.TemporaryDirectory() as artifact_root, patch.dict(
            os.environ,
            {
                "WORKER_REQUIRED_CHECKS": "lint",
                "WORKER_ARTIFACT_ROOT": artifact_root,
            },
            clear=False,
        ), patch.object(worker_orchestrator, "SessionLocal", self.session_factory), patch.object(
            worker_orchestrator, "acquire_slot_lease", side_effect=self._fake_acquire_slot_lease
        ), patch.object(
            worker_orchestrator,
            "reset_and_seed_slot",
            side_effect=RuntimeError("seed bootstrap failed"),
        ), patch.object(worker_orchestrator, "assign_worktree", side_effect=self._fake_assign_worktree), patch.object(
            worker_orchestrator, "run_codex_command"
        ) as run_codex_mock, patch.object(worker_orchestrator, "build_codex_command", return_value=["codex", "run"]):
            orchestrator = worker_orchestrator.WorkerOrchestrator()
            processed = orchestrator.process_next_run()

        self.assertTrue(processed)
        run_codex_mock.assert_not_called()

        with self.session_factory() as db:
            run = db.query(Run).filter(Run.id == self.run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")

            lease = db.query(SlotLease).filter(SlotLease.slot_id == "preview-1").first()
            self.assertIsNotNone(lease)
            self.assertEqual(lease.lease_state, "released")

            failed_event = (
                db.query(RunEvent)
                .filter(
                    RunEvent.run_id == self.run_id,
                    RunEvent.event_type == "status_transition",
                    RunEvent.status_to == "failed",
                )
                .order_by(RunEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(failed_event)
            self.assertEqual(failed_event.payload.get("failure_reason_code"), "MIGRATION_FAILED")


if __name__ == "__main__":
    unittest.main()
