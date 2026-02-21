from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
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
from app.models import PreviewDbReset, Run, RunArtifact, RunContext, RunEvent, ValidationCheck  # noqa: E402
from app.services.git_worktree_manager import assign_worktree  # noqa: E402
from app.services.preview_db_reset import db_name_for_slot, normalize_slot, reset_and_seed_slot  # noqa: E402
from app.services.run_event_log import append_run_event  # noqa: E402
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


@dataclass(frozen=True)
class AutoCommitResult:
    committed: bool
    commit_sha: str | None
    changed_file_count: int
    reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PreviewPublishResult:
    published: bool
    web_root_path: str | None
    dist_path: str | None
    log_artifact_uri: str
    file_count: int
    dependency_sync_log_artifact_uri: str | None = None
    migration_log_artifact_uri: str | None = None
    backend_restart_log_artifact_uri: str | None = None
    readiness_log_artifact_uri: str | None = None
    frontend_health_url: str | None = None
    backend_health_url: str | None = None
    error: str | None = None


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
                metadata_json = dict(run_context.metadata_json)
                metadata_json.setdefault("trace_id", trace_id)
                run_context.metadata_json = metadata_json
            else:
                run_context.metadata_json = {"trace_id": trace_id}

            append_run_event(
                db,
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload={"source": "worker", "phase": "claim", "trace_id": trace_id},
                actor_id=run.created_by,
                audit_action="run.plan.claimed",
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
        if not self._reset_preview_db_for_claimed_run(claimed):
            return

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

            auto_commit = self._commit_run_worktree_changes(claimed.run_id, claimed.worktree_path)
            if auto_commit.error:
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=FailureReasonCode.UNKNOWN_ERROR,
                    result=result,
                    extra_payload={"commit_error": auto_commit.error},
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            if auto_commit.changed_file_count > 0 and not auto_commit.committed:
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=FailureReasonCode.UNKNOWN_ERROR,
                    result=result,
                    extra_payload={
                        "commit_error": "commit_required_for_detected_changes",
                        "changed_file_count": auto_commit.changed_file_count,
                        "commit_reason": auto_commit.reason,
                    },
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            if auto_commit.commit_sha:
                run.commit_sha = auto_commit.commit_sha
                append_run_event(
                    db,
                    run_id=run.id,
                    event_type="run_commit_resolved",
                    payload={
                        "source": "worker",
                        "commit_sha": auto_commit.commit_sha,
                        "trace_id": claimed.trace_id,
                        "auto_committed": auto_commit.committed,
                        "changed_file_count": auto_commit.changed_file_count,
                        "reason": auto_commit.reason,
                    },
                    actor_id=run.created_by,
                    audit_action="run.edit.commit_resolved",
                )
                if auto_commit.committed:
                    append_run_event(
                        db,
                        run_id=run.id,
                        event_type="run_commit_created",
                        payload={
                            "source": "worker",
                            "commit_sha": auto_commit.commit_sha,
                            "trace_id": claimed.trace_id,
                            "changed_file_count": auto_commit.changed_file_count,
                        },
                        actor_id=run.created_by,
                        audit_action="run.edit.commit_created",
                    )
                emit_worker_log(
                    event="run_commit_resolved",
                    trace_id=claimed.trace_id,
                    run_id=run.id,
                    slot_id=claimed.slot_id,
                    commit_sha=auto_commit.commit_sha,
                    auto_committed=auto_commit.committed,
                    changed_file_count=auto_commit.changed_file_count,
                )

            status_from, status_to = transition_run_status(run, target=RunState.TESTING)
            append_run_event(
                db,
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload={
                    "source": "worker",
                    "check": "codex_cli_execution",
                    "trace_id": claimed.trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.test.started",
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

            publish_result = self._publish_preview_surface(
                db=db,
                run=run,
                claimed=claimed,
                trace_id=claimed.trace_id,
            )
            if not publish_result.published:
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=FailureReasonCode.PREVIEW_PUBLISH_FAILED,
                    result=result,
                    extra_payload={
                        "preview_publish_error": publish_result.error,
                        "preview_publish_log": publish_result.log_artifact_uri,
                        "preview_dependency_sync_log": publish_result.dependency_sync_log_artifact_uri,
                        "preview_migration_log": publish_result.migration_log_artifact_uri,
                        "preview_backend_restart_log": publish_result.backend_restart_log_artifact_uri,
                        "preview_readiness_log": publish_result.readiness_log_artifact_uri,
                        "preview_web_root": publish_result.web_root_path,
                        "preview_dist_path": publish_result.dist_path,
                        "preview_frontend_health_url": publish_result.frontend_health_url,
                        "preview_backend_health_url": publish_result.backend_health_url,
                    },
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            integration_result = self._run_slot_backend_integration_check(
                db=db,
                run=run,
                claimed=claimed,
                should_cancel=should_cancel,
                on_tick=on_tick,
                trace_id=claimed.trace_id,
                backend_health_url=publish_result.backend_health_url
                or f"http://127.0.0.1:{8100 + int(self._slot_suffix(claimed.slot_id))}/health",
            )
            if not integration_result.ok:
                failed_result = integration_result.failed_result or result
                self._finalize_failed_run(
                    db=db,
                    run=run,
                    slot_id=claimed.slot_id,
                    failure_reason=integration_result.failure_reason or FailureReasonCode.CHECKS_FAILED,
                    result=failed_result,
                    extra_payload={"failed_check": integration_result.failed_check_name},
                    trace_id=claimed.trace_id,
                )
                db.commit()
                return

            self._finalize_success_run(db=db, run=run, result=result, trace_id=claimed.trace_id)
            db.commit()

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _preview_reset_strategy() -> str:
        strategy = os.getenv("WORKER_PREVIEW_RESET_STRATEGY", "seed").strip().lower() or "seed"
        if strategy not in {"seed", "snapshot"}:
            return "seed"
        return strategy

    @staticmethod
    def _preview_seed_version() -> str:
        return os.getenv("WORKER_PREVIEW_SEED_VERSION", "v1").strip() or "v1"

    @staticmethod
    def _preview_snapshot_version() -> str | None:
        value = os.getenv("WORKER_PREVIEW_SNAPSHOT_VERSION", "").strip()
        return value or None

    def _reset_preview_db_for_claimed_run(self, claimed: ClaimedRun) -> bool:
        strategy = self._preview_reset_strategy()
        seed_version = self._preview_seed_version()
        snapshot_version = self._preview_snapshot_version()
        dry_run = self._env_bool("WORKER_PREVIEW_RESET_DRY_RUN", default=False)

        reset_id: int | None = None
        try:
            db_name = db_name_for_slot(claimed.slot_id)
        except ValueError as exc:
            self.logger.error("Invalid slot id for preview reset %s: %s", claimed.slot_id, exc)
            return self._finalize_preview_reset_failure(
                claimed=claimed,
                error=str(exc),
                strategy=strategy,
                seed_version=seed_version,
                snapshot_version=snapshot_version,
                dry_run=dry_run,
                reset_id=None,
            )

        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == claimed.run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return False
            if run.status == RunState.CANCELED.value:
                append_run_event(
                    db,
                    run_id=run.id,
                    event_type="worker_skipped_canceled_before_execution",
                    payload={
                        "source": "worker",
                        "slot_id": claimed.slot_id,
                        "trace_id": claimed.trace_id,
                    },
                    actor_id=run.created_by,
                    audit_action="run.edit.skipped_canceled",
                )
                release_slot_lease(db=db, slot_id=claimed.slot_id, run_id=claimed.run_id)
                db.commit()
                return False

            reset_record = PreviewDbReset(
                run_id=claimed.run_id,
                slot_id=claimed.slot_id,
                db_name=db_name,
                strategy=strategy,
                seed_version=seed_version,
                snapshot_version=snapshot_version,
                reset_status="running",
                details_json={"source": "worker", "dry_run": dry_run},
            )
            db.add(reset_record)
            db.flush()
            reset_id = reset_record.id

            append_run_event(
                db,
                run_id=claimed.run_id,
                event_type="preview_db_reset_started",
                payload={
                    "source": "worker",
                    "slot_id": claimed.slot_id,
                    "db_name": db_name,
                    "strategy": strategy,
                    "seed_version": seed_version,
                    "snapshot_version": snapshot_version,
                    "dry_run": dry_run,
                    "trace_id": claimed.trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.preview.reset_started",
            )
            db.commit()

        try:
            result = reset_and_seed_slot(
                slot_id=claimed.slot_id,
                run_id=claimed.run_id,
                seed_version=seed_version,
                strategy=strategy,
                snapshot_version=snapshot_version,
                dry_run=dry_run,
            )
        except Exception as exc:
            return self._finalize_preview_reset_failure(
                claimed=claimed,
                error=str(exc),
                strategy=strategy,
                seed_version=seed_version,
                snapshot_version=snapshot_version,
                dry_run=dry_run,
                reset_id=reset_id,
            )

        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == claimed.run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return False

            if reset_id is not None:
                reset_record = db.query(PreviewDbReset).filter(PreviewDbReset.id == reset_id).with_for_update().first()
                if reset_record is not None:
                    reset_record.reset_status = "completed"
                    reset_record.reset_completed_at = utcnow()
                    reset_record.details_json = dict(result)

            append_run_event(
                db,
                run_id=claimed.run_id,
                event_type="preview_db_reset_completed",
                payload={
                    "source": "worker",
                    "slot_id": claimed.slot_id,
                    "db_name": db_name,
                    "strategy": strategy,
                    "seed_version": seed_version,
                    "snapshot_version": snapshot_version,
                    "dry_run": dry_run,
                    "details": result,
                    "trace_id": claimed.trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.preview.reset_completed",
            )
            db.commit()

        emit_worker_log(
            event="preview_db_reset_completed",
            trace_id=claimed.trace_id,
            run_id=claimed.run_id,
            slot_id=claimed.slot_id,
            strategy=strategy,
            seed_version=seed_version,
            snapshot_version=snapshot_version,
            dry_run=dry_run,
        )
        return True

    def _finalize_preview_reset_failure(
        self,
        *,
        claimed: ClaimedRun,
        error: str,
        strategy: str,
        seed_version: str,
        snapshot_version: str | None,
        dry_run: bool,
        reset_id: int | None,
    ) -> bool:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == claimed.run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return False

            if reset_id is not None:
                reset_record = db.query(PreviewDbReset).filter(PreviewDbReset.id == reset_id).with_for_update().first()
                if reset_record is not None:
                    reset_record.reset_status = "failed"
                    reset_record.reset_completed_at = utcnow()
                    reset_record.details_json = {"error": error}

            append_run_event(
                db,
                run_id=claimed.run_id,
                event_type="preview_db_reset_failed",
                payload={
                    "source": "worker",
                    "slot_id": claimed.slot_id,
                    "strategy": strategy,
                    "seed_version": seed_version,
                    "snapshot_version": snapshot_version,
                    "dry_run": dry_run,
                    "error": error,
                    "trace_id": claimed.trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.preview.reset_failed",
            )

            if run.status != RunState.CANCELED.value:
                try:
                    status_from, status_to = transition_run_status(
                        run,
                        target=RunState.FAILED,
                        failure_reason=FailureReasonCode.MIGRATION_FAILED,
                    )
                    append_run_event(
                        db,
                        run_id=run.id,
                        event_type="status_transition",
                        status_from=status_from,
                        status_to=status_to,
                        payload={
                            "source": "worker",
                            "failure_reason_code": FailureReasonCode.MIGRATION_FAILED.value,
                            "reason": "preview_db_reset_failed",
                            "error": error,
                            "trace_id": claimed.trace_id,
                        },
                        actor_id=run.created_by,
                        audit_action="run.preview.reset_failure_terminal",
                    )
                except TransitionRuleError:
                    pass

            release_slot_lease(db=db, slot_id=claimed.slot_id, run_id=claimed.run_id)
            db.commit()

        emit_worker_log(
            event="run_failed",
            level=logging.WARNING,
            trace_id=claimed.trace_id,
            run_id=claimed.run_id,
            slot_id=claimed.slot_id,
            failure_reason_code=FailureReasonCode.MIGRATION_FAILED.value,
            reason="preview_db_reset_failed",
            error=error,
        )
        return False

    def _mark_editing(self, run_id: str, slot_id: str, trace_id: str | None) -> bool:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).with_for_update().first()
            if run is None:
                db.rollback()
                return False
            if run.status == RunState.CANCELED.value:
                append_run_event(
                    db,
                    run_id=run.id,
                    event_type="worker_skipped_canceled_before_execution",
                    payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                    actor_id=run.created_by,
                    audit_action="run.edit.skipped_canceled",
                )
                release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
                db.commit()
                return False

            status_from, status_to = transition_run_status(run, target=RunState.EDITING)
            append_run_event(
                db,
                run_id=run.id,
                event_type="status_transition",
                status_from=status_from,
                status_to=status_to,
                payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                actor_id=run.created_by,
                audit_action="run.edit.started",
            )
            append_run_event(
                db,
                run_id=run.id,
                event_type="codex_command_started",
                payload={"source": "worker", "slot_id": slot_id, "trace_id": trace_id},
                actor_id=run.created_by,
                audit_action="run.edit.command_started",
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
        append_run_event(
            db,
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
            actor_id=run.created_by,
            audit_action="run.edit.completed",
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

    @staticmethod
    def _git_author_env() -> dict[str, str]:
        name = os.getenv("WORKER_GIT_AUTHOR_NAME", "Ouroboros Worker")
        email = os.getenv("WORKER_GIT_AUTHOR_EMAIL", "worker@ouroboros.local")
        return {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }

    def _run_git_worktree(self, worktree_path: Path, args: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", "-C", str(worktree_path), *args],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **self._git_author_env()},
        )
        if proc.returncode != 0 and not allow_failure:
            detail = (proc.stderr.strip() or proc.stdout.strip() or "unknown_error").replace("\n", " ")
            raise ValueError(f"git_command_failed:{detail}")
        return proc

    def _commit_run_worktree_changes(self, run_id: str, worktree_path: Path) -> AutoCommitResult:
        expected_branch = f"codex/run-{run_id}"
        branch_proc = self._run_git_worktree(worktree_path, ["branch", "--show-current"], allow_failure=True)
        current_branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
        if branch_proc.returncode != 0:
            detail = (branch_proc.stderr.strip() or branch_proc.stdout.strip() or "unknown_error").replace("\n", " ")
            return AutoCommitResult(
                committed=False,
                commit_sha=self._resolve_worktree_commit_sha(worktree_path),
                changed_file_count=0,
                error=f"git_branch_probe_failed:{detail}",
            )
        if current_branch != expected_branch:
            checkout_proc = self._run_git_worktree(
                worktree_path,
                ["checkout", expected_branch],
                allow_failure=True,
            )
            if checkout_proc.returncode != 0:
                detail = (
                    checkout_proc.stderr.strip() or checkout_proc.stdout.strip() or "unknown_error"
                ).replace("\n", " ")
                return AutoCommitResult(
                    committed=False,
                    commit_sha=self._resolve_worktree_commit_sha(worktree_path),
                    changed_file_count=0,
                    error=f"git_checkout_expected_branch_failed:{detail}",
                )

        status = self._run_git_worktree(worktree_path, ["status", "--porcelain", "--untracked-files=all"])
        changed_lines = [line for line in status.stdout.splitlines() if line.strip()]
        if not changed_lines:
            return AutoCommitResult(
                committed=False,
                commit_sha=self._resolve_worktree_commit_sha(worktree_path),
                changed_file_count=0,
                reason="no_changes",
            )

        self._run_git_worktree(worktree_path, ["add", "-A"])
        commit_message = f"run({run_id}): apply generated changes"
        commit_proc = self._run_git_worktree(
            worktree_path,
            ["commit", "--no-gpg-sign", "-m", commit_message],
            allow_failure=True,
        )
        if commit_proc.returncode != 0:
            detail = (commit_proc.stderr.strip() or commit_proc.stdout.strip() or "unknown_error").replace("\n", " ")
            if "nothing to commit" in detail.lower():
                post_status = self._run_git_worktree(
                    worktree_path,
                    ["status", "--porcelain", "--untracked-files=all"],
                )
                post_changed_lines = [line for line in post_status.stdout.splitlines() if line.strip()]
                return AutoCommitResult(
                    committed=False,
                    commit_sha=self._resolve_worktree_commit_sha(worktree_path),
                    changed_file_count=max(len(changed_lines), len(post_changed_lines)),
                    error="git_commit_invariant_breach:nothing_to_commit_with_detected_changes",
                )
            return AutoCommitResult(
                committed=False,
                commit_sha=None,
                changed_file_count=len(changed_lines),
                error=f"git_commit_failed:{detail}",
            )

        return AutoCommitResult(
            committed=True,
            commit_sha=self._resolve_worktree_commit_sha(worktree_path),
            changed_file_count=len(changed_lines),
            reason="committed",
        )

    @staticmethod
    def _preview_publish_timeout_seconds() -> int:
        raw = os.getenv("WORKER_PREVIEW_PUBLISH_TIMEOUT_SECONDS", "900")
        try:
            return max(30, int(raw))
        except ValueError:
            return 900

    @staticmethod
    def _preview_web_root_template() -> str:
        default = str(REPO_ROOT / "infra" / "web-preview-{slot}")
        return os.getenv("WORKER_PREVIEW_WEB_ROOT_TEMPLATE", default).strip() or default

    @staticmethod
    def _slot_suffix(slot_id: str) -> str:
        normalized = normalize_slot(slot_id)
        suffix = normalized.removeprefix("preview")
        if suffix and suffix.isdigit():
            return suffix
        raise ValueError(f"invalid_slot_suffix:{slot_id}")

    def _preview_web_root_for_slot(self, slot_id: str) -> Path:
        suffix = self._slot_suffix(slot_id)
        template = self._preview_web_root_template()
        resolved = template.replace("{slot}", suffix).replace("{slot_id}", slot_id)
        return Path(resolved).expanduser().resolve()

    def _run_publish_command(
        self,
        *,
        command: list[str],
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str],
        log_handle,
    ) -> str | None:
        command_text = " ".join(shlex.quote(part) for part in command)
        log_handle.write(f"$ {command_text}\n")
        log_handle.flush()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            log_handle.write(f"[error] command timeout after {timeout_seconds}s: {command_text}\n")
            log_handle.flush()
            return f"preview_publish_timeout:{command_text}"

        if proc.stdout:
            log_handle.write(proc.stdout)
        if proc.stderr:
            log_handle.write(proc.stderr)
        log_handle.flush()

        if proc.returncode != 0:
            return f"preview_publish_command_failed:{command_text}:exit_{proc.returncode}"
        return None

    @staticmethod
    def _sync_directory_contents(source: Path, destination: Path) -> int:
        destination.mkdir(parents=True, exist_ok=True)

        for child in destination.iterdir():
            if child.name == ".gitignore":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        file_count = 0
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target)
                file_count += sum(1 for path in target.rglob("*") if path.is_file())
            else:
                shutil.copy2(child, target)
                file_count += 1
        return file_count

    def _publish_preview_surface(
        self,
        *,
        db,
        run: Run,
        claimed: ClaimedRun,
        trace_id: str | None,
    ) -> PreviewPublishResult:
        started_at = utcnow()
        artifact_dir = self.artifact_root / run.id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = artifact_dir / "preview.publish.log"
        dependency_log_path = artifact_dir / "preview.dependency-sync.log"
        migration_log_path = artifact_dir / "preview.migration.log"
        restart_log_path = artifact_dir / "preview.backend-restart.log"
        readiness_log_path = artifact_dir / "preview.readiness.log"
        frontend_root = claimed.worktree_path / "frontend"
        backend_root = claimed.worktree_path / "backend"
        dist_root = frontend_root / "dist"
        web_root = self._preview_web_root_for_slot(claimed.slot_id)
        timeout_seconds = self._preview_publish_timeout_seconds()
        artifact_uri = str(log_path)
        dependency_artifact_uri = str(dependency_log_path)
        migration_artifact_uri = str(migration_log_path)
        restart_artifact_uri = str(restart_log_path)
        readiness_artifact_uri = str(readiness_log_path)
        slot_suffix = self._slot_suffix(claimed.slot_id)
        slot_index = int(slot_suffix)
        slot_backend_port = 8100 + slot_index
        slot_frontend_port = 3100 + slot_index
        slot_backend_url = f"http://127.0.0.1:{slot_backend_port}"
        frontend_health_url = f"http://127.0.0.1:{slot_frontend_port}/health"
        backend_health_url = f"{slot_backend_url}/health"
        preview_api_base_url = os.getenv("WORKER_PREVIEW_API_BASE_URL", "/api").strip() or "/api"

        append_run_event(
            db,
            run_id=run.id,
            event_type="preview_publish_started",
            payload={
                "source": "worker",
                "slot_id": claimed.slot_id,
                "worktree_path": str(claimed.worktree_path),
                "frontend_root": str(frontend_root),
                "backend_root": str(backend_root),
                "web_root": str(web_root),
                "slot_backend_url": slot_backend_url,
                "frontend_health_url": frontend_health_url,
                "backend_health_url": backend_health_url,
                "preview_api_base_url": preview_api_base_url,
                "trace_id": trace_id,
            },
            actor_id=run.created_by,
            audit_action="run.preview.publish_started",
        )

        publish_error: str | None = None
        file_count = 0
        step_status: dict[str, str] = {
            "dependency_sync": "skipped",
            "slot_migration": "skipped",
            "backend_restart": "skipped",
            "readiness_gate": "skipped",
        }

        command_env = {
            **os.environ,
            **self._build_execution_env(
                trace_id=trace_id,
                run_id=run.id,
                slot_id=claimed.slot_id,
                commit_sha=run.commit_sha,
                check_name="preview_publish",
            ),
            "VITE_API_BASE_URL": preview_api_base_url,
            "VITE_SLOT_BACKEND_URL": slot_backend_url,
            "SLOT_ID": claimed.slot_id,
            "SLOT_BACKEND_URL": slot_backend_url,
        }

        def _run_step(
            *,
            step_name: str,
            command: list[str],
            cwd: Path,
            log_file: Path,
            timeout_override: int | None = None,
        ) -> str | None:
            command_text = " ".join(shlex.quote(part) for part in command)
            with log_file.open("a", encoding="utf-8") as step_log_handle:
                step_log_handle.write(f"step={step_name}\n")
                step_log_handle.write(f"cwd={cwd}\n")
                step_log_handle.write(f"$ {command_text}\n")
                step_log_handle.flush()
                return self._run_publish_command(
                    command=command,
                    cwd=cwd,
                    timeout_seconds=timeout_override or timeout_seconds,
                    env=command_env,
                    log_handle=step_log_handle,
                )

        with log_path.open("w", encoding="utf-8") as log_handle:
            log_handle.write(f"run_id={run.id}\n")
            log_handle.write(f"slot_id={claimed.slot_id}\n")
            log_handle.write(f"worktree_path={claimed.worktree_path}\n")
            log_handle.write(f"frontend_root={frontend_root}\n")
            log_handle.write(f"backend_root={backend_root}\n")
            log_handle.write(f"web_root={web_root}\n")
            log_handle.write(f"vite_api_base_url={preview_api_base_url}\n")
            log_handle.write(f"slot_backend_url={slot_backend_url}\n")
            log_handle.write(f"frontend_health_url={frontend_health_url}\n")
            log_handle.write(f"backend_health_url={backend_health_url}\n")
            log_handle.write(f"timeout_seconds={timeout_seconds}\n\n")
            log_handle.flush()

            npm_bin = shutil.which("npm")
            if not npm_bin:
                publish_error = "preview_publish_missing_npm"
            elif not frontend_root.exists() or not frontend_root.is_dir():
                publish_error = f"preview_publish_frontend_root_missing:{frontend_root}"
            elif not (frontend_root / "package.json").exists():
                publish_error = f"preview_publish_package_json_missing:{frontend_root / 'package.json'}"
            else:
                if not (frontend_root / "node_modules").exists():
                    install_error = self._run_publish_command(
                        command=[npm_bin, "ci", "--no-audit", "--no-fund"],
                        cwd=frontend_root,
                        timeout_seconds=timeout_seconds,
                        env=command_env,
                        log_handle=log_handle,
                    )
                    if install_error:
                        publish_error = install_error
                else:
                    log_handle.write("[info] npm install skipped (node_modules already present)\n")
                    log_handle.flush()

                if not publish_error:
                    build_error = self._run_publish_command(
                        command=[npm_bin, "run", "build"],
                        cwd=frontend_root,
                        timeout_seconds=timeout_seconds,
                        env=command_env,
                        log_handle=log_handle,
                    )
                    if build_error:
                        publish_error = build_error

                if not publish_error:
                    if not dist_root.exists() or not dist_root.is_dir():
                        publish_error = f"preview_publish_dist_missing:{dist_root}"
                    else:
                        file_count = self._sync_directory_contents(dist_root, web_root)
                        log_handle.write(f"[info] copied {file_count} files into {web_root}\n")
                        log_handle.flush()

                if not publish_error:
                    if not backend_root.exists() or not backend_root.is_dir():
                        publish_error = f"preview_publish_backend_root_missing:{backend_root}"
                    else:
                        step_status["dependency_sync"] = "running"
                        venv_path = backend_root / ".venv"
                        if not (venv_path / "bin" / "pip").exists():
                            sync_error = _run_step(
                                step_name="dependency_sync_create_venv",
                                command=["python3", "-m", "venv", ".venv"],
                                cwd=backend_root,
                                log_file=dependency_log_path,
                            )
                            if sync_error:
                                publish_error = f"preview_dependency_sync_failed:{sync_error}"

                        if not publish_error:
                            sync_error = _run_step(
                                step_name="dependency_sync_install",
                                command=[
                                    str(backend_root / ".venv" / "bin" / "pip"),
                                    "install",
                                    "--upgrade",
                                    "pip",
                                ],
                                cwd=backend_root,
                                log_file=dependency_log_path,
                            )
                            if sync_error:
                                publish_error = f"preview_dependency_sync_failed:{sync_error}"

                        if not publish_error:
                            sync_error = _run_step(
                                step_name="dependency_sync_install_editable",
                                command=[
                                    str(backend_root / ".venv" / "bin" / "pip"),
                                    "install",
                                    "-e",
                                    ".",
                                ],
                                cwd=backend_root,
                                log_file=dependency_log_path,
                            )
                            if sync_error:
                                publish_error = f"preview_dependency_sync_failed:{sync_error}"

                        step_status["dependency_sync"] = "failed" if publish_error else "passed"

                if not publish_error:
                    step_status["slot_migration"] = "running"
                    migration_error = _run_step(
                        step_name="slot_migration",
                        command=[
                            str(REPO_ROOT / "scripts" / "preview-slot-migrate.sh"),
                            "--slot",
                            claimed.slot_id,
                            "--worktree-path",
                            str(claimed.worktree_path),
                        ],
                        cwd=claimed.worktree_path,
                        log_file=migration_log_path,
                    )
                    if migration_error:
                        publish_error = f"preview_slot_migration_failed:{migration_error}"
                        step_status["slot_migration"] = "failed"
                    else:
                        step_status["slot_migration"] = "passed"

                if not publish_error:
                    step_status["backend_restart"] = "running"
                    restart_error = _run_step(
                        step_name="backend_restart",
                        command=[
                            str(REPO_ROOT / "scripts" / "preview-backend-runtime.sh"),
                            "restart",
                            "--slot",
                            claimed.slot_id,
                            "--worktree-path",
                            str(claimed.worktree_path),
                            "--health-timeout-seconds",
                            str(max(5, int(os.getenv("WORKER_PREVIEW_BACKEND_HEALTH_TIMEOUT_SECONDS", "30")))),
                        ],
                        cwd=claimed.worktree_path,
                        log_file=restart_log_path,
                    )
                    if restart_error:
                        publish_error = f"preview_backend_restart_failed:{restart_error}"
                        step_status["backend_restart"] = "failed"
                    else:
                        step_status["backend_restart"] = "passed"

                if not publish_error:
                    step_status["readiness_gate"] = "running"
                    frontend_health_error = _run_step(
                        step_name="frontend_health",
                        command=["curl", "-fsS", "--max-time", "5", frontend_health_url],
                        cwd=claimed.worktree_path,
                        log_file=readiness_log_path,
                    )
                    if frontend_health_error:
                        publish_error = f"preview_frontend_health_failed:{frontend_health_error}"
                    else:
                        backend_health_error = _run_step(
                            step_name="backend_health",
                            command=["curl", "-fsS", "--max-time", "5", backend_health_url],
                            cwd=claimed.worktree_path,
                            log_file=readiness_log_path,
                        )
                        if backend_health_error:
                            publish_error = f"preview_backend_health_failed:{backend_health_error}"
                    step_status["readiness_gate"] = "failed" if publish_error else "passed"

        ended_at = utcnow()
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="preview_publish_log",
                artifact_uri=artifact_uri,
                metadata_json={
                    "slot_id": claimed.slot_id,
                    "frontend_root": str(frontend_root),
                    "dist_root": str(dist_root),
                    "web_root": str(web_root),
                    "file_count": file_count,
                    "status": "failed" if publish_error else "passed",
                    "frontend_health_url": frontend_health_url,
                    "backend_health_url": backend_health_url,
                    "step_status": step_status,
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="preview_dependency_sync_log",
                artifact_uri=dependency_artifact_uri,
                metadata_json={
                    "slot_id": claimed.slot_id,
                    "status": step_status["dependency_sync"],
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="preview_migration_log",
                artifact_uri=migration_artifact_uri,
                metadata_json={
                    "slot_id": claimed.slot_id,
                    "status": step_status["slot_migration"],
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="preview_backend_restart_log",
                artifact_uri=restart_artifact_uri,
                metadata_json={
                    "slot_id": claimed.slot_id,
                    "status": step_status["backend_restart"],
                    "trace_id": trace_id,
                },
            )
        )
        db.add(
            RunArtifact(
                run_id=run.id,
                artifact_type="preview_readiness_log",
                artifact_uri=readiness_artifact_uri,
                metadata_json={
                    "slot_id": claimed.slot_id,
                    "status": step_status["readiness_gate"],
                    "frontend_health_url": frontend_health_url,
                    "backend_health_url": backend_health_url,
                    "trace_id": trace_id,
                },
            )
        )

        duration_seconds = max(0.0, (ended_at - started_at).total_seconds())
        if publish_error:
            append_run_event(
                db,
                run_id=run.id,
                event_type="preview_publish_failed",
                payload={
                    "source": "worker",
                    "slot_id": claimed.slot_id,
                    "worktree_path": str(claimed.worktree_path),
                    "frontend_root": str(frontend_root),
                    "dist_root": str(dist_root),
                    "web_root": str(web_root),
                    "artifact_uri": artifact_uri,
                    "dependency_sync_artifact_uri": dependency_artifact_uri,
                    "migration_artifact_uri": migration_artifact_uri,
                    "backend_restart_artifact_uri": restart_artifact_uri,
                    "readiness_artifact_uri": readiness_artifact_uri,
                    "frontend_health_url": frontend_health_url,
                    "backend_health_url": backend_health_url,
                    "step_status": step_status,
                    "duration_seconds": duration_seconds,
                    "error": publish_error,
                    "trace_id": trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.preview.publish_failed",
            )
            emit_worker_log(
                event="preview_publish_failed",
                level=logging.WARNING,
                trace_id=trace_id,
                run_id=run.id,
                slot_id=claimed.slot_id,
                commit_sha=run.commit_sha,
                web_root=str(web_root),
                error=publish_error,
            )
            return PreviewPublishResult(
                published=False,
                web_root_path=str(web_root),
                dist_path=str(dist_root),
                log_artifact_uri=artifact_uri,
                file_count=file_count,
                dependency_sync_log_artifact_uri=dependency_artifact_uri,
                migration_log_artifact_uri=migration_artifact_uri,
                backend_restart_log_artifact_uri=restart_artifact_uri,
                readiness_log_artifact_uri=readiness_artifact_uri,
                frontend_health_url=frontend_health_url,
                backend_health_url=backend_health_url,
                error=publish_error,
            )

        append_run_event(
            db,
            run_id=run.id,
            event_type="preview_publish_completed",
            payload={
                "source": "worker",
                "slot_id": claimed.slot_id,
                "worktree_path": str(claimed.worktree_path),
                "frontend_root": str(frontend_root),
                "dist_root": str(dist_root),
                "web_root": str(web_root),
                "artifact_uri": artifact_uri,
                "dependency_sync_artifact_uri": dependency_artifact_uri,
                "migration_artifact_uri": migration_artifact_uri,
                "backend_restart_artifact_uri": restart_artifact_uri,
                "readiness_artifact_uri": readiness_artifact_uri,
                "frontend_health_url": frontend_health_url,
                "backend_health_url": backend_health_url,
                "step_status": step_status,
                "duration_seconds": duration_seconds,
                "file_count": file_count,
                "trace_id": trace_id,
            },
            actor_id=run.created_by,
            audit_action="run.preview.publish_completed",
        )
        emit_worker_log(
            event="preview_publish_completed",
            trace_id=trace_id,
            run_id=run.id,
            slot_id=claimed.slot_id,
            commit_sha=run.commit_sha,
            web_root=str(web_root),
            file_count=file_count,
        )
        return PreviewPublishResult(
            published=True,
            web_root_path=str(web_root),
            dist_path=str(dist_root),
            log_artifact_uri=artifact_uri,
            file_count=file_count,
            dependency_sync_log_artifact_uri=dependency_artifact_uri,
            migration_log_artifact_uri=migration_artifact_uri,
            backend_restart_log_artifact_uri=restart_artifact_uri,
            readiness_log_artifact_uri=readiness_artifact_uri,
            frontend_health_url=frontend_health_url,
            backend_health_url=backend_health_url,
            error=None,
        )

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

            append_run_event(
                db,
                run_id=run.id,
                event_type="validation_check_started",
                payload={
                    "source": "worker",
                    "check_name": check.name,
                    "command": check.command,
                    "trace_id": trace_id,
                },
                actor_id=run.created_by,
                audit_action="run.test.check_started",
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
            append_run_event(
                db,
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
                actor_id=run.created_by,
                audit_action="run.test.check_completed",
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

    def _run_slot_backend_integration_check(
        self,
        *,
        db,
        run: Run,
        claimed: ClaimedRun,
        should_cancel,
        on_tick,
        trace_id: str | None,
        backend_health_url: str,
    ) -> ValidationPipelineResult:
        check_name = "slot_backend_integration"
        backend_api_base_url = backend_health_url.removesuffix("/health")
        check_started_at = utcnow()
        output_path = self.artifact_root / run.id / "checks" / f"{check_name}.log"

        append_run_event(
            db,
            run_id=run.id,
            event_type="validation_check_started",
            payload={
                "source": "worker",
                "check_name": check_name,
                "backend_api_base_url": backend_api_base_url,
                "slot_id": claimed.slot_id,
                "trace_id": trace_id,
            },
            actor_id=run.created_by,
            audit_action="run.test.check_started",
        )

        smoke_script = (
            "import json,sys,urllib.request\n"
            "base=sys.argv[1].rstrip('/')\n"
            "slot_id=sys.argv[2]\n"
            "run_id=sys.argv[3]\n"
            "with urllib.request.urlopen(f'{base}/health', timeout=5) as health_resp:\n"
            "    health_body=health_resp.read().decode('utf-8', errors='replace').strip()\n"
            "    if health_resp.status != 200:\n"
            "        raise RuntimeError(f'backend_health_status:{health_resp.status}')\n"
            "heartbeat_request=urllib.request.Request(\n"
            "  f'{base}/api/slots/{slot_id}/heartbeat',\n"
            "  data=json.dumps({'run_id': run_id}).encode('utf-8'),\n"
            "  headers={'Content-Type': 'application/json'},\n"
            "  method='POST',\n"
            ")\n"
            "with urllib.request.urlopen(heartbeat_request, timeout=10) as heartbeat_resp:\n"
            "    heartbeat=json.loads(heartbeat_resp.read().decode('utf-8'))\n"
            "if not heartbeat.get('heartbeat_updated'):\n"
            "    raise RuntimeError('slot_heartbeat_not_updated')\n"
            "with urllib.request.urlopen(f'{base}/api/slots', timeout=10) as slots_resp:\n"
            "    slots=json.loads(slots_resp.read().decode('utf-8'))\n"
            "slot_state=next((item for item in slots if item.get('slot_id') == slot_id), None)\n"
            "if slot_state is None:\n"
            "    raise RuntimeError('slot_state_missing')\n"
            "if slot_state.get('run_id') != run_id:\n"
            "    raise RuntimeError('slot_state_run_mismatch')\n"
            "print(json.dumps({\n"
            "  'status': 'ok',\n"
            "  'slot_id': slot_id,\n"
            "  'backend_api_base_url': base,\n"
            "  'health_body': health_body,\n"
            "  'slot_lease_probe': 'heartbeat',\n"
            "  'heartbeat_expires_at': heartbeat.get('expires_at'),\n"
            "  'slot_heartbeat_at': slot_state.get('heartbeat_at'),\n"
            "}, sort_keys=True))\n"
        )

        result = run_codex_command(
            command=["python3", "-c", smoke_script, backend_api_base_url, claimed.slot_id, run.id],
            worktree_path=claimed.worktree_path,
            output_path=output_path,
            timeout_seconds=max(30, int(os.getenv("WORKER_SLOT_BACKEND_SMOKE_TIMEOUT_SECONDS", "120"))),
            poll_interval_seconds=self.poll_interval_seconds,
            should_cancel=should_cancel,
            on_tick=on_tick,
            env=self._build_execution_env(
                trace_id=trace_id,
                run_id=run.id,
                slot_id=claimed.slot_id,
                commit_sha=run.commit_sha,
                check_name=check_name,
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
                check_name=check_name,
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
                    "check_name": check_name,
                    "status": check_status,
                    "backend_api_base_url": backend_api_base_url,
                    "slot_id": claimed.slot_id,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "canceled": result.canceled,
                    "lease_expired": result.lease_expired,
                    "trace_id": trace_id,
                },
            )
        )
        append_run_event(
            db,
            run_id=run.id,
            event_type="validation_check_finished",
            payload={
                "source": "worker",
                "check_name": check_name,
                "status": check_status,
                "backend_api_base_url": backend_api_base_url,
                "slot_id": claimed.slot_id,
                "artifact_uri": artifact_uri,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "canceled": result.canceled,
                "lease_expired": result.lease_expired,
                "duration_seconds": result.duration_seconds,
                "output_excerpt": result.output_excerpt,
                "trace_id": trace_id,
            },
            actor_id=run.created_by,
            audit_action="run.test.check_completed",
        )
        emit_worker_log(
            event="validation_check_finished",
            trace_id=trace_id,
            run_id=run.id,
            slot_id=claimed.slot_id,
            commit_sha=run.commit_sha,
            check_name=check_name,
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
                failed_check_name=check_name,
                failed_result=result,
            )

        return ValidationPipelineResult(ok=True)

    def _finalize_success_run(self, *, db, run: Run, result, trace_id: str | None) -> None:
        status_from, status_to = transition_run_status(run, target=RunState.PREVIEW_READY)
        append_run_event(
            db,
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
            actor_id=run.created_by,
            audit_action="run.test.completed",
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
