from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.domain.run_state_machine import (
    FailureReasonCode,
    RunState,
    TransitionRuleError,
    ensure_transition_allowed,
    list_failure_reason_codes,
    list_run_states,
)
from app.models import Run, RunEvent

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    title: str
    prompt: str
    route: str | None = None
    created_by: str | None = None


class TransitionRunRequest(BaseModel):
    to_status: RunState
    failure_reason_code: FailureReasonCode | None = None


class RunResponse(BaseModel):
    id: str
    title: str
    prompt: str
    status: str
    route: str | None
    slot_id: str | None
    branch_name: str | None
    worktree_path: str | None
    commit_sha: str | None
    parent_run_id: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


def _to_run_response(run: Run) -> RunResponse:
    return RunResponse(
        id=run.id,
        title=run.title,
        prompt=run.prompt,
        status=run.status,
        route=run.route,
        slot_id=run.slot_id,
        branch_name=run.branch_name,
        worktree_path=run.worktree_path,
        commit_sha=run.commit_sha,
        parent_run_id=run.parent_run_id,
        created_by=run.created_by,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _get_run_or_404(db: Session, run_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/contract")
def run_contract() -> dict[str, Any]:
    return {
        "states": list_run_states(),
        "failure_reason_codes": list_failure_reason_codes(),
    }


@router.post("", response_model=RunResponse)
def create_run(payload: CreateRunRequest, db: Session = Depends(get_db_session)) -> RunResponse:
    run = Run(
        title=payload.title,
        prompt=payload.prompt,
        status=RunState.QUEUED.value,
        route=payload.route,
        created_by=payload.created_by,
    )
    db.add(run)
    db.flush()

    db.add(
        RunEvent(
            run_id=run.id,
            event_type="run_created",
            status_to=RunState.QUEUED.value,
            payload={"source": "api"},
        )
    )

    db.commit()
    db.refresh(run)
    return _to_run_response(run)


@router.get("", response_model=list[RunResponse])
def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> list[RunResponse]:
    query = db.query(Run)
    if status:
        query = query.filter(Run.status == status)
    runs = query.order_by(Run.created_at.desc()).limit(limit).all()
    return [_to_run_response(run) for run in runs]


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    run = _get_run_or_404(db, run_id)
    return _to_run_response(run)


@router.post("/{run_id}/transition", response_model=RunResponse)
def transition_run(
    run_id: str,
    payload: TransitionRunRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    run = _get_run_or_404(db, run_id)

    current_state = RunState(run.status)
    target_state = payload.to_status

    try:
        ensure_transition_allowed(current_state, target_state, payload.failure_reason_code)
    except TransitionRuleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    run.status = target_state.value

    event_payload: dict[str, Any] = {}
    if payload.failure_reason_code is not None:
        event_payload["failure_reason_code"] = payload.failure_reason_code.value

    db.add(
        RunEvent(
            run_id=run.id,
            event_type="status_transition",
            status_from=current_state.value,
            status_to=target_state.value,
            payload=event_payload or None,
        )
    )

    db.commit()
    db.refresh(run)
    return _to_run_response(run)


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    payload = TransitionRunRequest(to_status=RunState.CANCELED)
    return transition_run(run_id=run_id, payload=payload, db=db)


@router.post("/{run_id}/retry", response_model=RunResponse)
def retry_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    parent_run = _get_run_or_404(db, run_id)

    child_run = Run(
        title=f"Retry: {parent_run.title}",
        prompt=parent_run.prompt,
        status=RunState.QUEUED.value,
        route=parent_run.route,
        created_by=parent_run.created_by,
        parent_run_id=parent_run.id,
    )
    db.add(child_run)
    db.flush()

    db.add(
        RunEvent(
            run_id=child_run.id,
            event_type="run_retried",
            status_to=RunState.QUEUED.value,
            payload={"parent_run_id": parent_run.id},
        )
    )

    db.commit()
    db.refresh(child_run)
    return _to_run_response(child_run)
