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
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


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
    current_state = RunState(run.status)
    target_state = RunState.APPROVED
    try:
        ensure_transition_allowed(current_state, target_state)
    except TransitionRuleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    run.status = target_state.value

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
            status_from=current_state.value,
            status_to=target_state.value,
            payload={"decision": "approved", "reason": payload.reason},
        )
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


@router.post("/runs/{run_id}/reject", response_model=ApprovalResponse)
def reject_run(run_id: str, payload: RejectRequest, db: Session = Depends(get_db_session)) -> ApprovalResponse:
    run = _get_run_or_404(db, run_id)
    current_state = RunState(run.status)
    target_state = RunState.FAILED
    try:
        ensure_transition_allowed(current_state, target_state, payload.failure_reason_code)
    except TransitionRuleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    run.status = target_state.value

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
            status_from=current_state.value,
            status_to=target_state.value,
            payload={
                "decision": "rejected",
                "reason": payload.reason,
                "failure_reason_code": payload.failure_reason_code.value,
            },
        )
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
