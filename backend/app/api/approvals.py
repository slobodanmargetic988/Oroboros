from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.domain.run_state_machine import (
    FailureReasonCode,
    RunState,
    TransitionRuleError,
    ensure_transition_allowed,
)
from app.models import Approval, Run, RunEvent
from app.services.merge_gate import merge_run_commit_to_main, run_merge_gate_checks
from app.services.slot_lease_manager import release_slot_lease

router = APIRouter(prefix="/api", tags=["approvals"])


class ApproveRequest(BaseModel):
    reviewer_id: str | None = None
    reason: str | None = None


class RejectRequest(BaseModel):
    reviewer_id: str | None = None
    reason: str
    failure_reason_code: FailureReasonCode = FailureReasonCode.POLICY_REJECTED


class ApprovalResponse(BaseModel):
    id: int
    run_id: str
    reviewer_id: str | None
    decision: str
    reason: str | None
    created_at: datetime


def _get_run_or_404(db: Session, run_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).with_for_update().first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _transition_or_409(
    run: Run,
    *,
    target: RunState,
    failure_reason: FailureReasonCode | None = None,
) -> tuple[str, str]:
    current_state = RunState(run.status)
    try:
        ensure_transition_allowed(current_state, target, failure_reason)
    except TransitionRuleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run.status = target.value
    return current_state.value, target.value


def _add_status_transition_event(
    db: Session,
    *,
    run: Run,
    status_from: str,
    status_to: str,
    payload: dict | None = None,
) -> None:
    db.add(
        RunEvent(
            run_id=run.id,
            event_type="status_transition",
            status_from=status_from,
            status_to=status_to,
            payload=payload,
        )
    )


@router.get("/runs/{run_id}/approvals", response_model=list[ApprovalResponse])
def list_run_approvals(run_id: str, db: Session = Depends(get_db_session)) -> list[ApprovalResponse]:
    approvals = (
        db.query(Approval)
        .filter(Approval.run_id == run_id)
        .order_by(Approval.created_at.asc(), Approval.id.asc())
        .all()
    )
    return [
        ApprovalResponse(
            id=item.id,
            run_id=item.run_id,
            reviewer_id=item.reviewer_id,
            decision=item.decision,
            reason=item.reason,
            created_at=item.created_at,
        )
        for item in approvals
    ]


@router.post("/runs/{run_id}/approve", response_model=ApprovalResponse)
def approve_run(run_id: str, payload: ApproveRequest, db: Session = Depends(get_db_session)) -> ApprovalResponse:
    run = _get_run_or_404(db, run_id)

    # Allow direct approve when run is preview_ready by advancing to needs_approval first.
    if RunState(run.status) == RunState.PREVIEW_READY:
        status_from, status_to = _transition_or_409(run, target=RunState.NEEDS_APPROVAL)
        _add_status_transition_event(
            db,
            run=run,
            status_from=status_from,
            status_to=status_to,
            payload={"source": "approve_endpoint", "phase": "auto_needs_approval"},
        )

    status_from, status_to = _transition_or_409(run, target=RunState.APPROVED)
    _add_status_transition_event(
        db,
        run=run,
        status_from=status_from,
        status_to=status_to,
        payload={"source": "approve_endpoint", "phase": "approved"},
    )

    approval = Approval(
        run_id=run.id,
        reviewer_id=payload.reviewer_id,
        decision="approved",
        reason=payload.reason,
    )
    db.add(
        RunEvent(
            run_id=run.id,
            event_type="approval_decision",
            status_from=status_from,
            status_to=status_to,
            payload={"decision": "approved", "reason": payload.reason},
        )
    )
    db.add(approval)

    gate_result = run_merge_gate_checks(db=db, run=run)
    if not gate_result.passed:
        failed_from, failed_to = _transition_or_409(
            run,
            target=RunState.FAILED,
            failure_reason=gate_result.failure_reason or FailureReasonCode.CHECKS_FAILED,
        )
        _add_status_transition_event(
            db,
            run=run,
            status_from=failed_from,
            status_to=failed_to,
            payload={
                "source": "merge_gate",
                "failure_reason_code": (gate_result.failure_reason or FailureReasonCode.CHECKS_FAILED).value,
                "failed_check": gate_result.failed_check,
                "detail": gate_result.detail,
            },
        )
        db.commit()
        db.refresh(approval)
        return ApprovalResponse(
            id=approval.id,
            run_id=approval.run_id,
            reviewer_id=approval.reviewer_id,
            decision=approval.decision,
            reason=approval.reason,
            created_at=approval.created_at,
        )

    merging_from, merging_to = _transition_or_409(run, target=RunState.MERGING)
    _add_status_transition_event(
        db,
        run=run,
        status_from=merging_from,
        status_to=merging_to,
        payload={"source": "merge_gate", "phase": "merge_start"},
    )

    merge_ok, merged_sha, merge_error = merge_run_commit_to_main(db=db, run=run)
    if not merge_ok:
        failed_from, failed_to = _transition_or_409(
            run,
            target=RunState.FAILED,
            failure_reason=FailureReasonCode.MERGE_CONFLICT,
        )
        _add_status_transition_event(
            db,
            run=run,
            status_from=failed_from,
            status_to=failed_to,
            payload={
                "source": "merge_gate",
                "failure_reason_code": FailureReasonCode.MERGE_CONFLICT.value,
                "detail": merge_error,
            },
        )
        db.commit()
        db.refresh(approval)
        return ApprovalResponse(
            id=approval.id,
            run_id=approval.run_id,
            reviewer_id=approval.reviewer_id,
            decision=approval.decision,
            reason=approval.reason,
            created_at=approval.created_at,
        )

    if merged_sha:
        run.commit_sha = merged_sha

    deploying_from, deploying_to = _transition_or_409(run, target=RunState.DEPLOYING)
    _add_status_transition_event(
        db,
        run=run,
        status_from=deploying_from,
        status_to=deploying_to,
        payload={"source": "merge_gate", "phase": "deploy_start"},
    )

    merged_from, merged_to = _transition_or_409(run, target=RunState.MERGED)
    _add_status_transition_event(
        db,
        run=run,
        status_from=merged_from,
        status_to=merged_to,
        payload={"source": "merge_gate", "phase": "merge_complete", "merged_commit_sha": run.commit_sha},
    )
    if run.slot_id:
        release_slot_id = run.slot_id
        release_result = release_slot_lease(db=db, slot_id=release_slot_id, run_id=run.id)
        if not release_result.get("released", False):
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="slot_release_skipped",
                    payload={
                        "source": "merge_gate",
                        "slot_id": release_slot_id,
                        "reason": release_result.get("reason"),
                    },
                )
            )

    db.commit()
    db.refresh(approval)

    return ApprovalResponse(
        id=approval.id,
        run_id=approval.run_id,
        reviewer_id=approval.reviewer_id,
        decision=approval.decision,
        reason=approval.reason,
        created_at=approval.created_at,
    )


@router.post("/runs/{run_id}/reject", response_model=ApprovalResponse)
def reject_run(run_id: str, payload: RejectRequest, db: Session = Depends(get_db_session)) -> ApprovalResponse:
    run = _get_run_or_404(db, run_id)
    status_from, status_to = _transition_or_409(
        run,
        target=RunState.FAILED,
        failure_reason=payload.failure_reason_code,
    )

    approval = Approval(
        run_id=run.id,
        reviewer_id=payload.reviewer_id,
        decision="rejected",
        reason=f"{payload.reason} [failure_reason_code={payload.failure_reason_code.value}]",
    )
    db.add(
        RunEvent(
            run_id=run.id,
            event_type="approval_decision",
            status_from=status_from,
            status_to=status_to,
            payload={
                "decision": "rejected",
                "reason": payload.reason,
                "failure_reason_code": payload.failure_reason_code.value,
            },
        )
    )
    _add_status_transition_event(
        db,
        run=run,
        status_from=status_from,
        status_to=status_to,
        payload={
            "source": "reject_endpoint",
            "failure_reason_code": payload.failure_reason_code.value,
            "reason": payload.reason,
        },
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    return ApprovalResponse(
        id=approval.id,
        run_id=approval.run_id,
        reviewer_id=approval.reviewer_id,
        decision=approval.decision,
        reason=approval.reason,
        created_at=approval.created_at,
    )
