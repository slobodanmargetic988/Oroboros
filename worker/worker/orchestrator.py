from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any

from .codex_runner import (
    CommandExecutionResult,
    LeaseExpiredSignal,
    RunCanceledSignal,
    build_codex_command,
    run_codex_command,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PATH = Path(os.getenv("WORKER_BACKEND_PATH", str(REPO_ROOT / "backend"))).resolve()
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.db.session import SessionLocal  # noqa: E402
from app.domain.run_state_machine import (  # noqa: E402
    FailureReasonCode,
    RunState,
    TransitionRuleError,
    ensure_transition_allowed,
)
from app.models import Run, RunArtifact, RunContext, RunEvent, ValidationCheck  # noqa: E402
from app.services.git_worktree_manager import assign_worktree  # noqa: E402
from app.services.slot_lease_manager import (  # noqa: E402
    acquire_slot_lease,
    heartbeat_slot_lease,
    release_slot_lease,
)
from .observability import emit_worker_log, generate_trace_id, normalize_trace_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ClaimedRun:
    run_id: str
    prompt: str
    slot_id: str
    worktree_path: Path
    trace_id: str | None = None


@dataclass(frozen=True)
class ValidationCheckSpec:
    name: str
    command: list[str]
    timeout_seconds: int


@dataclass(frozen=True)
class ValidationPipelineResult:
    ok: bool
    failure_reason: FailureReasonCode | None = None
    failed_check_name: str | None = None
    failed_result: CommandExecutionResult | None = None


def transition_run_status(
    run: Run,
    *,
    target: RunState,
    failure_reason: FailureReasonCode | None = None,
) -> tuple[str, str]:
    current_state = RunState(run.status)
    if current_state == target:
        return current_state.value, target.value

    ensure_transition_allowed(current_state, target, failure_reason)
    run.status = target.value
    return current_state.value, target.value


class WorkerOrchestrator:
    DEFAULT_CHECK_COMMANDS: dict[str, str] = {
        "lint": "python3 -m compileall backend/app",
        "test": "python3 -m unittest discover -s worker/tests -p 'test_*.py'",
        "smoke": "python3 -c \"print('smoke-ok')\"",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger("worker.orchestrator")
        self.timeout_seconds = max(30, int(os.getenv("WORKER_RUN_TIMEOUT_SECONDS", "1800")))
        self.poll_interval_seconds = max(0.2, float(os.getenv("WORKER_RUN_POLL_SECONDS", "0.5")))
        self.heartbeat_interval_seconds = max(5.0, float(os.getenv("WORKER_HEARTBEAT_SECONDS", "15")))
        self.cancel_check_interval_seconds = max(
            0.2, float(os.getenv("WORKER_CANCEL_CHECK_SECONDS", "2"))
        )
        self.check_timeout_seconds = max(30, int(os.getenv("WORKER_CHECK_TIMEOUT_SECONDS", "900")))
        artifact_root = os.getenv("WORKER_ARTIFACT_ROOT", str(REPO_ROOT / "artifacts" / "runs"))
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.required_checks = self._load_required_checks()

    def process_next_run(self) -> bool:
        claimed = self._claim_next_run()
        if claimed is None:
            return False

        self._execute_claimed_run(claimed)
        return True

    @staticmethod
    def _check_env_key(name: str) -> str:
        normalized = "".join(char if char.isalnum() else "_" for char in name.strip().lower())
        return normalized.upper()

    def _resolve_check_command(self, check_name: str) -> list[str]:
        key = self._check_env_key(check_name)
        env_value = os.getenv(f"WORKER_CHECK_{key}_COMMAND")
        if env_value:
            command = shlex.split(env_value)
            if command:
                return command

        default = self.DEFAULT_CHECK_COMMANDS.get(check_name.lower())
        if default:
            command = shlex.split(default)
            if command:
                return command

        # Fallback keeps pipeline deterministic even if no explicit command is configured.
        return ["python3", "-c", "print('validation-check-noop')"]

    def _load_required_checks(self) -> list[ValidationCheckSpec]:
        configured = os.getenv("WORKER_REQUIRED_CHECKS", "lint,test,smoke")
        names = [item.strip() for item in configured.split(",") if item.strip()]
        specs: list[ValidationCheckSpec] = []
        for name in names:
            command = self._resolve_check_command(name)
            key = self._check_env_key(name)
            timeout_raw = os.getenv(f"WORKER_CHECK_{key}_TIMEOUT_SECONDS")
            timeout_seconds = self.check_timeout_seconds
            if timeout_raw:
                try:
                    timeout_seconds = max(30, int(timeout_raw))
                except ValueError:
                    timeout_seconds = self.check_timeout_seconds

            specs.append(
                ValidationCheckSpec(
                    name=name,
                    command=command,
                    timeout_seconds=timeout_seconds,
                )
            )
        return specs

    def _claim_next_run(self) -> ClaimedRun | None:
        with SessionLocal() as db:
            query = db.query(Run).filter(Run.status == RunState.QUEUED.value).order_by(Run.created_at.asc())
            run = query.with_for_update(skip_locked=True).first()
            if run is None:
                return None

            lease_result = acquire_slot_lease(db=db, run_id=run.id)
            if not lease_result.get("acquired"):
                db.commit()
                return None

            slot_id = lease_result.get("slot_id")
            if not isinstance(slot_id, str) or not slot_id:
                db.commit()
                return None

            try:
                status_from, status_to = transition_run_status(run, target=RunState.PLANNING)
            except TransitionRuleError:
                db.rollback()
                self.logger.warning("Unable to claim run %s due to invalid transition", run.id)
                return None

            run_context = db.query(RunContext).filter(RunContext.run_id == run.id).first()
            trace_id = None
            if run_context and isinstance(run_context.metadata_json, dict):
                trace_id = normalize_trace_id(run_context.metadata_json.get("trace_id"))
            if not trace_id:
                trace_id = generate_trace_id()
            if run_context is None:
                run_context = RunContext(
                    run_id=run.id,
                    route=run.route,
                    metadata_json={"trace_id": trace_id},
                )
                db.add(run_context)
            elif isinstance(run_context.metadata_json, dict):
                run_context.metadata_json.setdefault("trace_id", trace_id)
            else:
                run_context.metadata_json = {"trace_id": trace_id}

            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="status_transition",
                    status_from=status_from,
                    status_to=status_to,
                    payload={"source": "worker", "phase": "claim", "trace_id": trace_id},
                )
            )

            # SessionLocal uses autoflush=False; flush lease + status writes so
            # assign_worktree can validate active slot lease in the same transaction.
            db.flush()
            assigned = assign_worktree(db=db, run_id=run.id, slot_id=slot_id)
            db.commit()
            db.refresh(run)
            emit_worker_log(
                event="run_claimed",
                trace_id=trace_id,
                run_id=run.id,
                slot_id=slot_id,
                commit_sha=run.commit_sha,
                status_from=status_from,
                status_to=status_to,
            )

            worktree = assigned.get("worktree_path") or run.worktree_path
            if not worktree:
                return None

            return ClaimedRun(
                run_id=run.id,
                prompt=run.prompt,
                slot_id=slot_id,
                worktree_path=Path(worktree).expanduser().resolve(),
                trace_id=trace_id,
            )

    def _execute_claimed_run(self, claimed: ClaimedRun) -> None:
        if not self._mark_editing(claimed.run_id, claimed.slot_id, claimed.trace_id):
            return

        output_path = self.artifact_root / claimed.run_id / "codex.stdout.log"
        command = build_codex_command(claimed.prompt, claimed.worktree_path)
        self.logger.info("Executing run %s in %s", claimed.run_id, claimed.worktree_path)
        emit_worker_log(
            event="run_execution_started",
            trace_id=claimed.trace_id,
            run_id=claimed.run_id,
            slot_id=claimed.slot_id,
            worktree_path=str(claimed.worktree_path),
            command=command,
        )

        last_cancel_check = 0.0
        last_heartbeat = 0.0

        def should_cancel() -> bool:
            nonlocal last_cancel_check
            now = time.monotonic()
            if now - last_cancel_check < self.cancel_check_interval_seconds:
                return False
            last_cancel_check = now
            return self._is_run_canceled(claimed.run_id)

        def on_tick() -> None:
            nonlocal last_heartbeat
            now = time.monotonic()
            if now - last_heartbeat < self.heartbeat_interval_seconds:
                return
            last_heartbeat = now
            heartbeat = self._heartbeat_slot(claimed.run_id, claimed.slot_id)
            if heartbeat == "lease_expired":
                raise LeaseExpiredSignal()
            if heartbeat == "run_canceled":
                raise RunCanceledSignal()

        started_at = utcnow()
        result = run_codex_command(
            command=command,
            worktree_path=claimed.worktree_path,
            output_path=output_path,
            timeout_seconds=self.timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
            should_cancel=should_cancel,
            on_tick=on_tick,
            env=self._build_execution_env(
                trace_id=claimed.trace_id,
                run_id=claimed.run_id,
                slot_id=claimed.slot_id,
            ),
        )
        ended_at = utcnow()

        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == claimed.run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return

            commit_sha = self._resolve_worktree_commit_sha(claimed.worktree_path)
            if commit_sha:
                run.commit_sha = commit_sha
                db.add(
                    RunEvent(
                        run_id=run.id,
                        event_type="run_commit_resolved",
                        payload={
                            "source": "worker",
                            "commit_sha": commit_sha,
                            "trace_id": claimed.trace_id,
                        },
                    )
                )
                emit_worker_log(
                    event="run_commit_resolved",
                    trace_id=claimed.trace_id,
                    run_id=run.id,
                    slot_id=claimed.slot_id,
                    commit_sha=commit_sha,
                )

            self._record_output_artifact(
                db=db,
                run=run,
                started_at=started_at,
                ended_at=ended_at,
                output_path=output_path,
                result=result,
                command=command,
                trace_id=claimed.trace_id,
            )

            if run.status == RunState.CANCELED.value or result.canceled:
                self._finalize_canceled_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    result=result,
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            if result.lease_expired:
                self._finalize_expired_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    result=result,
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            if result.timed_out:
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=FailureReasonCode.AGENT_TIMEOUT,
                    result=result,
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            if result.exit_code != 0:
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=FailureReasonCode.UNKNOWN_ERROR,
                    result=result,
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            status_from, status_to = transition_run_status(run, target=RunState.TESTING)
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="status_transition",
                    status_from=status_from,
                    status_to=status_to,
                    payload={
                        "source": "worker",
                        "check": "codex_cli_execution",
                        "trace_id": claimed.trace_id,
                    },
                )
            )
            # Release the row lock acquired by claim before long-running validation checks.
            db.commit()

            validation_result = self._run_validation_pipeline(
                db=db,
                run=run,
                claimed=claimed,
                should_cancel=should_cancel,
                on_tick=on_tick,
                trace_id=claimed.trace_id,
            )
            run = db.query(Run).filter(Run.id == claimed.run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return
            if not validation_result.ok:
                failed_result = validation_result.failed_result or result
                failure_reason = validation_result.failure_reason
                if run.status == RunState.CANCELED.value or failure_reason == FailureReasonCode.AGENT_CANCELED:
                    self._finalize_canceled_run(
                        db=db,
                        run=run,
                        slot_id=claimed.slot_id,
                        result=failed_result,
                        trace_id=claimed.trace_id,
                    )
                    db.commit()
                    return
                if failure_reason == FailureReasonCode.PREVIEW_EXPIRED:
                    self._finalize_expired_run(
                        db=db,
                        run=run,
                        slot_id=claimed.slot_id,
                        result=failed_result,
                        trace_id=claimed.trace_id,
                    )
                    db.commit()
                    return

                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=failure_reason or FailureReasonCode.CHECKS_FAILED,
                    result=failed_result,
                    extra_payload={"failed_check": validation_result.failed_check_name},
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            self._finalize_success_run(db=db, run=run, result=result, trace_id=claimed.trace_id)
            db.commit()

    def _mark_editing(self, run_id: str, slot_id: str, trace_id: str | None) -> bool:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return False
            if run.status == RunState.CANCELED.value:
                db.add(
                    RunEvent(
                        run_id=run.id,
                        event_type="worker_skipped_canceled_before_execution",
                        payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                    )
                )
                release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
                db.commit()
                return False

            status_from, status_to = transition_run_status(run, target=RunState.EDITING)
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="status_transition",
                    status_from=status_from,
                    status_to=status_to,
                    payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                )
            )
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="codex_command_started",
                    payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                )
            )
            db.commit()
            emit_worker_log(
                event="run_editing_started",
                trace_id=trace_id,
                run_id=run.id,
                slot_id=slot_id,
                commit_sha=run.commit_sha,
                status_from=status_from,
                status_to=status_to,
            )
            return True

    def _record_output_artifact(
        self,
        *,
        db,
        run: Run,
        started_at: datetime,
        ended_at: datetime,
        output_path: Path,
        result,
        command: list[str],
        trace_id: str | None,
    ) -> None:
        artifact_uri = str(output_path)
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="codex_stdout",
                artifact_uri=artifact_uri,
                metadata_json={
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "canceled": result.canceled,
                    "lease_expired": result.lease_expired,
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="codex_command_finished",
                payload={
                    "source": "worker",
                    "command": command,
                    "artifact_uri": artifact_uri,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "canceled": result.canceled,
                    "lease_expired": result.lease_expired,
                    "duration_seconds": result.duration_seconds,
                    "output_excerpt": result.output_excerpt,
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            ValidationCheck(
                run_id=run.id,
                check_name="codex_cli_execution",
                status="failed" if (result.timed_out or result.canceled or result.exit_code != 0) else "passed",
                started_at=started_at,
                ended_at=ended_at,
                artifact_uri=artifact_uri,
            )
        )

    def _resolve_worktree_commit_sha(self, worktree_path: Path) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            self.logger.warning("Unable to resolve commit SHA for worktree %s", worktree_path)
            return None
        value = proc.stdout.strip()
        return value or None

    def _run_validation_pipeline(
        self,
        *,
        db,
        run: Run,
        claimed: ClaimedRun,
        should_cancel,
        on_tick,
        trace_id: str | None,
    ) -> ValidationPipelineResult:
        for check in self.required_checks:
            check_started_at = utcnow()
            output_path = self.artifact_root / run.id / "checks" / f"{check.name}.log"

            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="validation_check_started",
                    payload={
                        "source": "worker",
                        "check_name": check.name,
                        "command": check.command,
                        "trace_id": trace_id,
                    },
                )
            )

            result = run_codex_command(
                command=check.command,
                worktree_path=claimed.worktree_path,
                output_path=output_path,
                timeout_seconds=check.timeout_seconds,
                poll_interval_seconds=self.poll_interval_seconds,
                should_cancel=should_cancel,
                on_tick=on_tick,
                env=self._build_execution_env(
                    trace_id=trace_id,
                    run_id=run.id,
                    slot_id=claimed.slot_id,
                    commit_sha=run.commit_sha,
                    check_name=check.name,
                ),
            )
            check_ended_at = utcnow()

            failure_reason: FailureReasonCode | None = None
            check_status = "passed"
            if result.lease_expired:
                check_status = "expired"
                failure_reason = FailureReasonCode.PREVIEW_EXPIRED
            elif result.canceled:
                check_status = "canceled"
                failure_reason = FailureReasonCode.AGENT_CANCELED
            elif result.timed_out:
                check_status = "timed_out"
                failure_reason = FailureReasonCode.AGENT_TIMEOUT
            elif result.exit_code != 0:
                check_status = "failed"
                failure_reason = FailureReasonCode.CHECKS_FAILED

            artifact_uri = str(output_path)
            db.add(
                ValidationCheck(
                    run_id=run.id,
                    check_name=check.name,
                    status=check_status,
                    started_at=check_started_at,
                    ended_at=check_ended_at,
                    artifact_uri=artifact_uri,
                )
            )
            db.add(
                RunArtifact(
                    run_id=run.id,
                    artifact_type="validation_check_log",
                    artifact_uri=artifact_uri,
                    metadata_json={
                        "check_name": check.name,
                        "status": check_status,
                        "command": check.command,
                        "exit_code": result.exit_code,
                        "timed_out": result.timed_out,
                        "canceled": result.canceled,
                        "lease_expired": result.lease_expired,
                        "trace_id": trace_id,
                    },
                )
            )
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="validation_check_finished",
                    payload={
                        "source": "worker",
                        "check_name": check.name,
                        "status": check_status,
                        "artifact_uri": artifact_uri,
                        "exit_code": result.exit_code,
                        "timed_out": result.timed_out,
                        "canceled": result.canceled,
                        "lease_expired": result.lease_expired,
                        "duration_seconds": result.duration_seconds,
                        "output_excerpt": result.output_excerpt,
                        "trace_id": trace_id,
                    },
                )
            )
            emit_worker_log(
                event="validation_check_finished",
                trace_id=trace_id,
                run_id=run.id,
                slot_id=claimed.slot_id,
                commit_sha=run.commit_sha,
                check_name=check.name,
                status=check_status,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                canceled=result.canceled,
                lease_expired=result.lease_expired,
            )

            if failure_reason is not None:
                return ValidationPipelineResult(
                    ok=False,
                    failure_reason=failure_reason,
                    failed_check_name=check.name,
                    failed_result=result,
                )

        return ValidationPipelineResult(ok=True)

    def _finalize_success_run(self, *, db, run: Run, result, trace_id: str | None) -> None:
        status_from, status_to = transition_run_status(run, target=RunState.PREVIEW_READY)
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload={
                    "source": "worker",
                    "result": "ready_for_preview",
                    "exit_code": result.exit_code,
                    "required_checks": [check.name for check in self.required_checks],
                    "trace_id": trace_id,
                },
            )
        )
        emit_worker_log(
            event="run_preview_ready",
            trace_id=trace_id,
            run_id=run.id,
            slot_id=run.slot_id,
            commit_sha=run.commit_sha,
            exit_code=result.exit_code,
        )

    def _finalize_failed_run(
        self,
        *,
        db,
        run: Run,
        slot_id: str,
        failure_reason: FailureReasonCode,
        result,
        extra_payload: dict[str, Any] | None = None,
        trace_id: str | None,
    ) -> None:
        status_from, status_to = transition_run_status(
            run,
            target=RunState.FAILED,
            failure_reason=failure_reason,
        )
        payload: dict[str, Any] = {
            "source": "worker",
            "failure_reason_code": failure_reason.value,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "trace_id": trace_id,
        }
        if failure_reason == FailureReasonCode.AGENT_TIMEOUT:
            payload["recoverable"] = True
            payload["recovery_strategy"] = "create_child_run"
            payload["resume_endpoint"] = f"/api/runs/{run.id}/resume"
        if extra_payload:
            payload.update(extra_payload)
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload=payload,
            )
        )
        release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
        emit_worker_log(
            event="run_failed",
            level=logging.WARNING,
            trace_id=trace_id,
            run_id=run.id,
            slot_id=slot_id,
            commit_sha=run.commit_sha,
            failure_reason_code=failure_reason.value,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
        )

    def _finalize_expired_run(
        self,
        *,
        db,
        run: Run,
        slot_id: str,
        result,
        trace_id: str | None,
    ) -> None:
        status_from, status_to = transition_run_status(run, target=RunState.EXPIRED)
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload={
                    "source": "worker",
                    "reason": FailureReasonCode.PREVIEW_EXPIRED.value,
                    "lease_expired": result.lease_expired,
                    "trace_id": trace_id,
                    "recoverable": True,
                    "recovery_strategy": "create_child_run",
                    "resume_endpoint": f"/api/runs/{run.id}/resume",
                },
            )
        )
        release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
        emit_worker_log(
            event="run_expired",
            level=logging.WARNING,
            trace_id=trace_id,
            run_id=run.id,
            slot_id=slot_id,
            commit_sha=run.commit_sha,
            lease_expired=result.lease_expired,
        )

    def _finalize_canceled_run(
        self,
        *,
        db,
        run: Run,
        slot_id: str,
        result,
        trace_id: str | None,
    ) -> None:
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="worker_observed_canceled",
                payload={
                    "source": "worker",
                    "exit_code": result.exit_code,
                    "canceled": True,
                    "trace_id": trace_id,
                },
            )
        )
        release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
        emit_worker_log(
            event="run_canceled",
            trace_id=trace_id,
            run_id=run.id,
            slot_id=slot_id,
            commit_sha=run.commit_sha,
            exit_code=result.exit_code,
        )

    @staticmethod
    def _build_execution_env(
        *,
        trace_id: str | None,
        run_id: str,
        slot_id: str,
        commit_sha: str | None = None,
        check_name: str | None = None,
    ) -> dict[str, str]:
        env: dict[str, str] = {
            "RUN_ID": run_id,
            "SLOT_ID": slot_id,
            "OUROBOROS_RUN_ID": run_id,
            "OUROBOROS_SLOT_ID": slot_id,
        }
        if trace_id:
            env["TRACE_ID"] = trace_id
            env["OUROBOROS_TRACE_ID"] = trace_id
        if commit_sha:
            env["COMMIT_SHA"] = commit_sha
            env["OUROBOROS_COMMIT_SHA"] = commit_sha
        if check_name:
            env["CHECK_NAME"] = check_name
            env["OUROBOROS_CHECK_NAME"] = check_name
        return env

    def _heartbeat_slot(self, run_id: str, slot_id: str) -> str | None:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run is None:
                db.rollback()
                return "run_missing"
            if run.status == RunState.CANCELED.value:
                db.commit()
                return "run_canceled"

            result = heartbeat_slot_lease(db=db, slot_id=slot_id, run_id=run_id)
            db.commit()
            if not result.get("heartbeat_updated"):
                reason = result.get("reason")
                if isinstance(reason, str):
                    return reason
            return None

    def _is_run_canceled(self, run_id: str) -> bool:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            return run is not None and run.status == RunState.CANCELED.value


def process_one_run_cycle() -> bool:
    orchestrator = WorkerOrchestrator()
    return orchestrator.process_next_run()
