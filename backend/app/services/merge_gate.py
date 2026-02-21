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


@dataclass(frozen=True)
class DeployReloadResult:
    passed: bool
    failure_reason: FailureReasonCode | None = None
    detail: str | None = None
    artifact_uri: str | None = None
    reload_command: list[str] | None = None
    healthcheck_command: list[str] | None = None


@dataclass(frozen=True)
class GitPushResult:
    passed: bool
    skipped: bool = False
    failure_reason: FailureReasonCode | None = None
    detail: str | None = None
    artifact_uri: str | None = None
    push_mode: str | None = None
    remote: str | None = None
    branch: str | None = None
    dry_run: bool = False
    rollback_guidance: str | None = None


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


def _shell_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _resolve_deploy_command(env_name: str, default: str) -> list[str]:
    raw = os.getenv(env_name, default).strip()
    command = shlex.split(raw)
    if not command:
        raise ValueError(f"missing_command:{env_name}")
    return command


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


def run_post_merge_git_push(run: Run) -> GitPushResult:
    push_mode_raw = os.getenv("MERGE_GATE_GIT_PUSH_MODE", "manual").strip().lower()
    if push_mode_raw in {"manual", "off", "disabled", "none"}:
        push_mode = "manual"
        dry_run = False
    elif push_mode_raw in {"auto", "enabled"}:
        push_mode = "auto"
        dry_run = False
    elif push_mode_raw in {"dry-run", "dry_run", "dryrun"}:
        push_mode = "dry-run"
        dry_run = True
    else:
        return GitPushResult(
            passed=False,
            failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
            detail=f"invalid_push_mode:{push_mode_raw}",
            push_mode=push_mode_raw or None,
        )

    remote = os.getenv("MERGE_GATE_GIT_PUSH_REMOTE", "origin").strip() or "origin"
    branch = os.getenv("MERGE_GATE_GIT_PUSH_BRANCH", "main").strip() or "main"
    timeout_raw = os.getenv("MERGE_GATE_GIT_PUSH_TIMEOUT_SECONDS", "120")
    try:
        timeout_seconds = max(15, int(timeout_raw))
    except ValueError:
        timeout_seconds = 120

    artifact_dir = _artifact_root() / run.id / "deploy"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "git-push.log"

    if push_mode == "manual":
        with artifact_path.open("w", encoding="utf-8") as log_handle:
            log_handle.write(f"run_id={run.id}\n")
            log_handle.write(f"commit_sha={run.commit_sha}\n")
            log_handle.write(f"push_mode={push_mode}\n")
            log_handle.write(f"remote={remote}\n")
            log_handle.write(f"branch={branch}\n")
            log_handle.write("result=push_skipped_manual_mode\n")
        return GitPushResult(
            passed=True,
            skipped=True,
            detail="push_skipped_manual_mode",
            artifact_uri=str(artifact_path),
            push_mode=push_mode,
            remote=remote,
            branch=branch,
            dry_run=False,
        )

    repo_path = _repo_root()
    if not (repo_path / ".git").exists():
        return GitPushResult(
            passed=False,
            failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
            detail="repo_root_not_found",
            push_mode=push_mode,
            remote=remote,
            branch=branch,
            dry_run=dry_run,
            artifact_uri=str(artifact_path),
        )

    def _run_git(args: list[str]) -> tuple[int | None, bool, str]:
        return _run_command(["git", *args], cwd=repo_path, timeout_seconds=timeout_seconds)

    def _log_command(
        log_handle: Any,
        *,
        label: str,
        command_parts: list[str],
        exit_code: int | None,
        timed_out: bool,
        output: str,
    ) -> None:
        log_handle.write(f"[{label}]\n")
        log_handle.write(f"command={_shell_command(command_parts)}\n")
        log_handle.write(f"exit_code={exit_code}\n")
        log_handle.write(f"timed_out={timed_out}\n")
        log_handle.write(output)
        if not output.endswith("\n"):
            log_handle.write("\n")
        log_handle.write("\n")
        log_handle.flush()

    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/{remote}/{branch}"
    rollback_guidance: str | None = None

    with artifact_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write(f"run_id={run.id}\n")
        log_handle.write(f"commit_sha={run.commit_sha}\n")
        log_handle.write(f"repo_path={repo_path}\n")
        log_handle.write(f"push_mode={push_mode}\n")
        log_handle.write(f"remote={remote}\n")
        log_handle.write(f"branch={branch}\n")
        log_handle.write(f"dry_run={dry_run}\n\n")

        check_remote_cmd = ["git", "remote", "get-url", remote]
        check_remote_exit, check_remote_timed_out, check_remote_output = _run_git(["remote", "get-url", remote])
        _log_command(
            log_handle,
            label="check_remote",
            command_parts=check_remote_cmd,
            exit_code=check_remote_exit,
            timed_out=check_remote_timed_out,
            output=check_remote_output,
        )
        if check_remote_timed_out:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="remote_check_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        if check_remote_exit != 0:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail=f"remote_check_failed:exit_{check_remote_exit}",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )

        local_head_cmd = ["git", "rev-parse", "--verify", local_ref]
        local_head_exit, local_head_timed_out, local_head_output = _run_git(["rev-parse", "--verify", local_ref])
        _log_command(
            log_handle,
            label="local_head",
            command_parts=local_head_cmd,
            exit_code=local_head_exit,
            timed_out=local_head_timed_out,
            output=local_head_output,
        )
        if local_head_timed_out:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="local_head_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        if local_head_exit != 0:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail=f"local_branch_missing:{branch}",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        local_head = local_head_output.strip()
        if run.commit_sha and local_head != run.commit_sha:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="local_branch_head_mismatch_run_commit",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )

        fetch_cmd = ["git", "fetch", "--prune", remote, branch]
        fetch_exit, fetch_timed_out, fetch_output = _run_git(["fetch", "--prune", remote, branch])
        _log_command(
            log_handle,
            label="fetch_remote_branch",
            command_parts=fetch_cmd,
            exit_code=fetch_exit,
            timed_out=fetch_timed_out,
            output=fetch_output,
        )
        if fetch_timed_out:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="fetch_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        if fetch_exit != 0:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail=f"fetch_failed:exit_{fetch_exit}",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )

        remote_head_cmd = ["git", "rev-parse", "--verify", remote_ref]
        remote_head_exit, remote_head_timed_out, remote_head_output = _run_git(["rev-parse", "--verify", remote_ref])
        _log_command(
            log_handle,
            label="remote_head",
            command_parts=remote_head_cmd,
            exit_code=remote_head_exit,
            timed_out=remote_head_timed_out,
            output=remote_head_output,
        )
        if remote_head_timed_out:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="remote_head_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        if remote_head_exit != 0:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail=f"remote_branch_missing:{remote}/{branch}",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        remote_head = remote_head_output.strip()

        ff_guard_cmd = ["git", "merge-base", "--is-ancestor", remote_ref, local_ref]
        ff_guard_exit, ff_guard_timed_out, ff_guard_output = _run_git(
            ["merge-base", "--is-ancestor", remote_ref, local_ref]
        )
        _log_command(
            log_handle,
            label="fast_forward_guard",
            command_parts=ff_guard_cmd,
            exit_code=ff_guard_exit,
            timed_out=ff_guard_timed_out,
            output=ff_guard_output,
        )
        if ff_guard_timed_out:
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="fast_forward_guard_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
            )
        if ff_guard_exit != 0:
            rollback_guidance = (
                f"Local {branch} is behind or diverged from {remote}/{branch}. "
                "Fetch/rebase manually before retrying push."
            )
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="non_fast_forward_guard_failed",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
                rollback_guidance=rollback_guidance,
            )

        push_args = ["push", "--porcelain"]
        if dry_run:
            push_args.append("--dry-run")
        push_args.extend([remote, f"{local_ref}:refs/heads/{branch}"])
        push_cmd = ["git", *push_args]
        push_exit, push_timed_out, push_output = _run_git(push_args)
        _log_command(
            log_handle,
            label="git_push",
            command_parts=push_cmd,
            exit_code=push_exit,
            timed_out=push_timed_out,
            output=push_output,
        )
        if push_timed_out:
            rollback_guidance = (
                f"Inspect {artifact_path}. If local rollback is required, run: "
                f"git -C {repo_path} switch {branch} && git -C {repo_path} reset --hard {remote_head}"
            )
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail="git_push_timeout",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
                rollback_guidance=rollback_guidance,
            )
        if push_exit != 0:
            rollback_guidance = (
                f"Inspect {artifact_path}. If local rollback is required, run: "
                f"git -C {repo_path} switch {branch} && git -C {repo_path} reset --hard {remote_head}"
            )
            return GitPushResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_PUSH_FAILED,
                detail=f"git_push_failed:exit_{push_exit}",
                artifact_uri=str(artifact_path),
                push_mode=push_mode,
                remote=remote,
                branch=branch,
                dry_run=dry_run,
                rollback_guidance=rollback_guidance,
            )

    return GitPushResult(
        passed=True,
        skipped=False,
        detail="push_dry_run_ok" if dry_run else "push_ok",
        artifact_uri=str(artifact_path),
        push_mode=push_mode,
        remote=remote,
        branch=branch,
        dry_run=dry_run,
    )


def run_post_merge_backend_reload(run: Run) -> DeployReloadResult:
    repo_path = _repo_root()
    if not (repo_path / ".git").exists():
        return DeployReloadResult(
            passed=False,
            failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
            detail="repo_root_not_found",
        )

    try:
        reload_command = _resolve_deploy_command(
            "MERGE_GATE_DEPLOY_BACKEND_RELOAD_COMMAND",
            "sudo systemctl reload-or-restart ouroboros-api",
        )
        healthcheck_command = _resolve_deploy_command(
            "MERGE_GATE_DEPLOY_BACKEND_HEALTHCHECK_COMMAND",
            "curl -fsS http://127.0.0.1:8000/health",
        )
    except ValueError as exc:
        return DeployReloadResult(
            passed=False,
            failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
            detail=str(exc),
        )

    timeout_seconds = max(15, int(os.getenv("MERGE_GATE_DEPLOY_TIMEOUT_SECONDS", "120")))
    artifact_dir = _artifact_root() / run.id / "deploy"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "backend-reload.log"

    with artifact_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write(f"run_id={run.id}\n")
        log_handle.write(f"commit_sha={run.commit_sha}\n")
        log_handle.write(f"repo_path={repo_path}\n")
        log_handle.write(f"reload_command={_shell_command(reload_command)}\n")
        log_handle.write(f"healthcheck_command={_shell_command(healthcheck_command)}\n\n")
        log_handle.flush()

        reload_exit, reload_timed_out, reload_output = _run_command(
            reload_command,
            cwd=repo_path,
            timeout_seconds=timeout_seconds,
        )
        log_handle.write("[reload]\n")
        log_handle.write(reload_output)
        log_handle.write("\n")
        if reload_timed_out:
            return DeployReloadResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
                detail="backend_reload_timeout",
                artifact_uri=str(artifact_path),
                reload_command=reload_command,
                healthcheck_command=healthcheck_command,
            )
        if reload_exit != 0:
            return DeployReloadResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
                detail=f"backend_reload_failed:exit_{reload_exit}",
                artifact_uri=str(artifact_path),
                reload_command=reload_command,
                healthcheck_command=healthcheck_command,
            )

        health_exit, health_timed_out, health_output = _run_command(
            healthcheck_command,
            cwd=repo_path,
            timeout_seconds=timeout_seconds,
        )
        log_handle.write("[healthcheck]\n")
        log_handle.write(health_output)
        log_handle.write("\n")
        log_handle.flush()

        if health_timed_out:
            return DeployReloadResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
                detail="backend_healthcheck_timeout",
                artifact_uri=str(artifact_path),
                reload_command=reload_command,
                healthcheck_command=healthcheck_command,
            )
        if health_exit != 0:
            return DeployReloadResult(
                passed=False,
                failure_reason=FailureReasonCode.DEPLOY_HEALTHCHECK_FAILED,
                detail=f"backend_healthcheck_failed:exit_{health_exit}",
                artifact_uri=str(artifact_path),
                reload_command=reload_command,
                healthcheck_command=healthcheck_command,
            )

    return DeployReloadResult(
        passed=True,
        artifact_uri=str(artifact_path),
        reload_command=reload_command,
        healthcheck_command=healthcheck_command,
    )
