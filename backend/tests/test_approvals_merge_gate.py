from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.api.approvals import ApproveRequest, RejectRequest, approve_run, reject_run
from app.db.base import Base
from app.domain.run_state_machine import FailureReasonCode
from app.models import Approval, AuditLog, Run, ValidationCheck
from app.services.merge_gate import MergeGateResult, run_merge_gate_checks


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalEndpointOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _create_run(self, *, status: str) -> str:
        with self.session_factory() as db:
            run = Run(
                title="Approval run",
                prompt="approve me",
                status=status,
                route="/codex",
                commit_sha="abc123",
                worktree_path="/tmp/worktree",
            )
            db.add(run)
            db.commit()
            return run.id

    def test_approve_blocks_merge_when_final_checks_fail(self) -> None:
        run_id = self._create_run(status="needs_approval")
        with self.session_factory() as db, patch(
            "app.api.approvals.run_merge_gate_checks",
            return_value=MergeGateResult(
                passed=False,
                failure_reason=FailureReasonCode.CHECKS_FAILED,
                failed_check="lint",
                detail="failed",
            ),
        ), patch("app.api.approvals.merge_run_commit_to_main") as merge_mock:
            response = approve_run(run_id, ApproveRequest(reviewer_id=None, reason="looks good"), db)

            self.assertEqual(response.decision, "approved")
            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")
            merge_mock.assert_not_called()

    def test_approve_runs_merge_path_when_checks_pass(self) -> None:
        run_id = self._create_run(status="preview_ready")
        with self.session_factory() as db, patch(
            "app.api.approvals.run_merge_gate_checks",
            return_value=MergeGateResult(passed=True),
        ), patch(
            "app.api.approvals.merge_run_commit_to_main",
            return_value=(True, "mergedsha", None),
        ):
            response = approve_run(run_id, ApproveRequest(reviewer_id=None, reason=None), db)

            self.assertEqual(response.decision, "approved")
            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "merged")
            self.assertEqual(run.commit_sha, "mergedsha")
            audit_actions = [item.action for item in db.query(AuditLog).order_by(AuditLog.id.asc()).all()]
            self.assertIn("run.approve.accepted", audit_actions)
            self.assertIn("run.merge.started", audit_actions)
            self.assertIn("run.deploy.started", audit_actions)
            self.assertIn("run.deploy.completed", audit_actions)

    def test_reject_transitions_to_failed_with_reason(self) -> None:
        run_id = self._create_run(status="needs_approval")
        with self.session_factory() as db, patch(
            "app.api.approvals.delete_run_branch",
            return_value={"deleted": True, "run_id": run_id, "branch_name": "codex/run-test", "reason": None},
        ) as delete_branch_mock:
            response = reject_run(
                run_id,
                RejectRequest(
                    reviewer_id=None,
                    reason="not acceptable",
                    failure_reason_code=FailureReasonCode.POLICY_REJECTED,
                ),
                db,
            )
            self.assertEqual(response.decision, "rejected")
            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")
            delete_branch_mock.assert_called_once_with(db=db, run_id=run_id, actor_id=None)

    def test_reject_allows_terminal_runs_without_state_change(self) -> None:
        run_id = self._create_run(status="merged")
        with self.session_factory() as db, patch("app.api.approvals.delete_run_branch") as delete_branch_mock:
            response = reject_run(
                run_id,
                RejectRequest(
                    reviewer_id=None,
                    reason="post-merge audit reject",
                    failure_reason_code=FailureReasonCode.POLICY_REJECTED,
                ),
                db,
            )
            self.assertEqual(response.decision, "rejected")
            run = db.query(Run).filter(Run.id == run_id).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "merged")
            delete_branch_mock.assert_not_called()


class MergeGateCommitPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _init_git_repo(self, path: Path) -> str:
        subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)
        (path / "README.md").write_text(f"seed-{_utcnow_iso()}\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=str(path), check=True, capture_output=True, text=True)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            check=True,
            capture_output=True,
            text=True,
        )
        return head.stdout.strip()

    def _create_run(self, *, status: str, commit_sha: str, worktree_path: str) -> str:
        with self.session_factory() as db:
            run = Run(
                title="Merge gate run",
                prompt="gate",
                status=status,
                route="/codex",
                commit_sha=commit_sha,
                worktree_path=worktree_path,
            )
            db.add(run)
            db.commit()
            return run.id

    def test_run_merge_gate_checks_passes_on_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp, patch.dict(
            os.environ,
            {
                "MERGE_GATE_REQUIRED_CHECKS": "smoke",
                "MERGE_GATE_CHECK_SMOKE_COMMAND": "python3 -c \"print('ok')\"",
            },
            clear=False,
        ):
            repo_path = Path(repo_tmp)
            commit_sha = self._init_git_repo(repo_path)
            run_id = self._create_run(status="approved", commit_sha=commit_sha, worktree_path=str(repo_path))

            with self.session_factory() as db:
                run = db.query(Run).filter(Run.id == run_id).first()
                self.assertIsNotNone(run)
                result = run_merge_gate_checks(db, run)
                db.commit()

                self.assertTrue(result.passed)
                rows = db.query(ValidationCheck).filter(ValidationCheck.run_id == run_id).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].check_name, "merge_gate:smoke")
                self.assertEqual(rows[0].status, "passed")
                self.assertTrue(rows[0].artifact_uri)

    def test_run_merge_gate_checks_fails_on_commit_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp:
            repo_path = Path(repo_tmp)
            first_sha = self._init_git_repo(repo_path)
            (repo_path / "README.md").write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=str(repo_path), check=True)
            subprocess.run(["git", "commit", "-m", "change"], cwd=str(repo_path), check=True, capture_output=True, text=True)

            run_id = self._create_run(status="approved", commit_sha=first_sha, worktree_path=str(repo_path))
            with self.session_factory() as db:
                run = db.query(Run).filter(Run.id == run_id).first()
                self.assertIsNotNone(run)
                result = run_merge_gate_checks(db, run)
                self.assertFalse(result.passed)
                self.assertEqual(result.failure_reason, FailureReasonCode.MERGE_CONFLICT)
                self.assertEqual(result.detail, "head_sha_mismatch_before_checks")


if __name__ == "__main__":
    unittest.main()
