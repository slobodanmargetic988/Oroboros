from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    EDITING = "editing"
    TESTING = "testing"
    PREVIEW_READY = "preview_ready"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    MERGING = "merging"
    DEPLOYING = "deploying"
    MERGED = "merged"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class FailureReasonCode(str, Enum):
    WAITING_FOR_SLOT = "WAITING_FOR_SLOT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CHECKS_FAILED = "CHECKS_FAILED"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    DEPLOY_PUSH_FAILED = "DEPLOY_PUSH_FAILED"
    DEPLOY_HEALTHCHECK_FAILED = "DEPLOY_HEALTHCHECK_FAILED"
    PREVIEW_PUBLISH_FAILED = "PREVIEW_PUBLISH_FAILED"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_CANCELED = "AGENT_CANCELED"
    PREVIEW_EXPIRED = "PREVIEW_EXPIRED"
    POLICY_REJECTED = "POLICY_REJECTED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


TERMINAL_STATES = {
    RunState.MERGED,
    RunState.FAILED,
    RunState.CANCELED,
    RunState.EXPIRED,
}

VALID_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.QUEUED: {RunState.PLANNING, RunState.CANCELED, RunState.FAILED, RunState.EXPIRED},
    RunState.PLANNING: {RunState.EDITING, RunState.CANCELED, RunState.FAILED, RunState.EXPIRED},
    RunState.EDITING: {RunState.TESTING, RunState.CANCELED, RunState.FAILED, RunState.EXPIRED},
    RunState.TESTING: {RunState.PREVIEW_READY, RunState.FAILED, RunState.CANCELED, RunState.EXPIRED},
    RunState.PREVIEW_READY: {RunState.NEEDS_APPROVAL, RunState.CANCELED, RunState.FAILED, RunState.EXPIRED},
    RunState.NEEDS_APPROVAL: {RunState.APPROVED, RunState.FAILED, RunState.CANCELED, RunState.EXPIRED},
    RunState.APPROVED: {RunState.MERGING, RunState.FAILED, RunState.CANCELED, RunState.EXPIRED},
    RunState.MERGING: {RunState.DEPLOYING, RunState.FAILED, RunState.CANCELED},
    RunState.DEPLOYING: {RunState.MERGED, RunState.FAILED, RunState.CANCELED},
    RunState.MERGED: set(),
    RunState.FAILED: set(),
    RunState.CANCELED: set(),
    RunState.EXPIRED: set(),
}


class TransitionRuleError(ValueError):
    """Raised when an invalid run state transition is requested."""


def ensure_transition_allowed(
    current: RunState,
    target: RunState,
    failure_reason: FailureReasonCode | None = None,
) -> None:
    if current in TERMINAL_STATES:
        raise TransitionRuleError(f"Cannot transition terminal state '{current.value}'.")

    allowed_targets = VALID_TRANSITIONS[current]
    if target not in allowed_targets:
        allowed_text = ", ".join(sorted(state.value for state in allowed_targets))
        raise TransitionRuleError(
            f"Invalid transition '{current.value}' -> '{target.value}'. Allowed: [{allowed_text}]"
        )

    if target == RunState.FAILED and failure_reason is None:
        raise TransitionRuleError("failure_reason_code is required when transitioning to failed.")

    if target != RunState.FAILED and failure_reason is not None:
        raise TransitionRuleError("failure_reason_code is only valid for failed transitions.")


def list_run_states() -> list[str]:
    return [state.value for state in RunState]


def list_failure_reason_codes() -> list[str]:
    return [code.value for code in FailureReasonCode]
