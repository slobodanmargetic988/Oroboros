from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.run_state_machine import FailureReasonCode
from app.models import Release, Run, RunArtifact, ValidationCheck
from app.services.run_event_log import append_run_event


class MergeGateConfigurationError(ValueError):
    def __init__(self, check_name: str) -> None:
        self.check_name = check_name
        super().__init__(f"missing_command_for_required_check:{check_name}")


@dataclass(frozen=True)
class MergeGateCheck:
    name: str
    command: list[str]
    timeout_seconds: int


@dataclass(frozen=True)
class MergeGateResult:
    passed: bool
    failure_reason: FailureReasonCode | None = None
    failed_check: str | None = None
    detail: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _artifact_root() -> Path:
    raw = os.getenv("WORKER_ARTIFACT_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "artifacts" / "runs").resolve()


def _check_env_key(name: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in name.strip().lower())
    return normalized.upper()


def _resolve_check_command(check_name: str) -> list[str]:
    key = _check_env_key(check_name)
    env_value = os.getenv(f"MERGE_GATE_CHECK_{key}_COMMAND")
    if env_value:
        parsed = shlex.split(env_value)
        if parsed:
            return parsed

    defaults = {
        "lint": "python3 -m compileall backend/app",
        "test": "python3 -m unittest discover -s worker/tests -p 'test_*.py'",
        "smoke": "python3 -c \"print('smoke-ok')\"",
    }
    default = defaults.get(check_name.lower())
    if default:
        parsed = shlex.split(default)
        if parsed:
            return parsed

    raise MergeGateConfigurationError(check_name)


def load_merge_gate_checks() -> list[MergeGateCheck]:
    configured = os.getenv("MERGE_GATE_REQUIRED_CHECKS", os.getenv("WORKER_REQUIRED_CHECKS", "lint,test,smoke"))
    names = [item.strip() for item in configured.split(",") if item.strip()]
    default_timeout = max(30, int(os.getenv("MERGE_GATE_CHECK_TIMEOUT_SECONDS", "900")))
    checks: list[MergeGateCheck] = []
    for name in names:
        key = _check_env_key(name)
        timeout = default_timeout
        timeout_override = os.getenv(f"MERGE_GATE_CHECK_{key}_TIMEOUT_SECONDS")
        if timeout_override:
            try:
                timeout = max(30, int(timeout_override))
            except ValueError:
                timeout = default_timeout
        checks.append(MergeGateCheck(name=name, command=_resolve_check_command(name), timeout_seconds=timeout))
    return checks


def _run_command(command: list[str], *, cwd: Path, timeout_seconds: int) -> tuple[int | None, bool, str]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        output = f"{proc.stdout}{proc.stderr}"
        return proc.returncode, False, output
    except subprocess.TimeoutExpired as exc:
        output = f"{exc.stdout or ''}{exc.stderr or ''}"
        return None, True, output


def _git_rev_parse(worktree_path: Path, revision: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(worktree_path), "rev-parse", revision],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def run_merge_gate_checks(db: Session, run: Run) -> MergeGateResult:
    if not run.commit_sha:
        return MergeGateResult(
            passed=False,
            failure_reason=FailureReasonCode.MERGE_CONFLICT,
            detail="missing_commit_sha",
        )
    if not run.worktree_path:
        return MergeGateResult(
            passed=False,
            failure_reason=FailureReasonCode.MERGE_CONFLICT,
            detail="missing_worktree_path",
        )

    worktree_path = Path(run.worktree_path).expanduser().resolve()
    expected_commit = run.commit_sha
    current_head = _git_rev_parse(worktree_path, "HEAD")
    if current_head != expected_commit:
        return MergeGateResult(
            passed=False,
            failure_reason=FailureReasonCode.MERGE_CONFLICT,
            detail="head_sha_mismatch_before_checks",
        )

    try:
        checks = load_merge_gate_checks()
    except MergeGateConfigurationError as exc:
        return MergeGateResult(
            passed=False,
            failure_reason=FailureReasonCode.CHECKS_FAILED,
            failed_check=exc.check_name,
            detail="missing_check_command_configuration",
        )
    artifact_dir = _artifact_root() / run.id / "merge-gate"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for check in checks:
        started_at = _utcnow()
        exit_code, timed_out, output = _run_command(
            check.command,
            cwd=worktree_path,
            timeout_seconds=check.timeout_seconds,
        )
        ended_at = _utcnow()

        artifact_path = artifact_dir / f"{check.name}.log"
        artifact_path.write_text(output, encoding="utf-8")
        artifact_uri = str(artifact_path)

        status = "passed"
        failure_reason = None
        if timed_out:
            status = "timed_out"
            failure_reason = FailureReasonCode.AGENT_TIMEOUT
        elif exit_code != 0:
            status = "failed"
            failure_reason = FailureReasonCode.CHECKS_FAILED

        db.add(
            ValidationCheck(
                run_id=run.id,
                check_name=f"merge_gate:{check.name}",
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                artifact_uri=artifact_uri,
            )
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="merge_gate_check_log",
                artifact_uri=artifact_uri,
                metadata_json={
                    "check_name": check.name,
                    "command": check.command,
                    "status": status,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "expected_commit_sha": expected_commit,
                },
            )
        )
        append_run_event(
            db,
            run_id=run.id,
            event_type="merge_gate_check_finished",
            payload={
                "check_name": check.name,
                "status": status,
                "artifact_uri": artifact_uri,
                "command": check.command,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "expected_commit_sha": expected_commit,
            },
            actor_id=run.created_by,
            audit_action="run.test.final_check_completed",
        )

        head_after_check = _git_rev_parse(worktree_path, "HEAD")
        if head_after_check != expected_commit:
            return MergeGateResult(
                passed=False,
                failure_reason=FailureReasonCode.MERGE_CONFLICT,
                failed_check=check.name,
                detail="head_sha_changed_during_checks",
            )

        if failure_reason is not None:
            return MergeGateResult(
                passed=False,
                failure_reason=failure_reason,
                failed_check=check.name,
                detail=status,
            )

    return MergeGateResult(passed=True)


def _repo_root() -> Path:
    settings = get_settings()
    return Path(settings.repo_root_path).expanduser().resolve()


def merge_run_commit_to_main(db: Session, run: Run) -> tuple[bool, str | None, str | None]:
    if not run.commit_sha:
        return False, None, "missing_commit_sha"

    repo_path = _repo_root()
    if not (repo_path / ".git").exists():
        return False, None, "repo_root_not_found"

    previous_branch_proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    previous_branch = previous_branch_proc.stdout.strip() if previous_branch_proc.returncode == 0 else None

    switch_main = subprocess.run(
        ["git", "-C", str(repo_path), "switch", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if switch_main.returncode != 0:
        return False, None, switch_main.stderr.strip() or "switch_main_failed"

    merge_proc = subprocess.run(
        ["git", "-C", str(repo_path), "merge", "--no-ff", "--no-edit", run.commit_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_proc.returncode != 0:
        subprocess.run(["git", "-C", str(repo_path), "merge", "--abort"], capture_output=True, text=True, check=False)
        if previous_branch:
            subprocess.run(
                ["git", "-C", str(repo_path), "switch", previous_branch],
                capture_output=True,
                text=True,
                check=False,
            )
        return False, None, merge_proc.stderr.strip() or merge_proc.stdout.strip() or "merge_failed"

    head_proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    merged_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else run.commit_sha

    if previous_branch:
        subprocess.run(
            ["git", "-C", str(repo_path), "switch", previous_branch],
            capture_output=True,
            text=True,
            check=False,
        )

    release_id = f"rel-{run.id[:8]}-{int(_utcnow().timestamp())}"
    db.add(
        Release(
            release_id=release_id,
            commit_sha=merged_sha,
            migration_marker=None,
            status="deployed",
            deployed_at=_utcnow(),
        )
    )
    return True, merged_sha, None
