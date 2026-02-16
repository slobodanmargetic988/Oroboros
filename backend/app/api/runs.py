from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import literal, or_
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
from app.models import Run, RunContext, RunEvent
from app.services.git_worktree_manager import cleanup_worktree
from app.services.run_event_log import append_run_event
from app.services.slot_lease_manager import release_slot_lease

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    title: str
    prompt: str
    route: str | None = None
    page_title: str | None = None
    element_hint: str | None = None
    note: str | None = None
    metadata: dict[str, Any] | None = None
    created_by: str | None = None


class TransitionRunRequest(BaseModel):
    to_status: RunState
    failure_reason_code: FailureReasonCode | None = None


class RunContextResponse(BaseModel):
    route: str | None = None
    page_title: str | None = None
    element_hint: str | None = None
    note: str | None = None
    metadata: dict[str, Any] | None = None


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
    context: RunContextResponse | None = None


class RunListResponse(BaseModel):
    items: list[RunResponse]
    total: int
    limit: int
    offset: int


RECOVERABLE_TIMEOUT_REASONS = {
    FailureReasonCode.AGENT_TIMEOUT.value,
    FailureReasonCode.PREVIEW_EXPIRED.value,
}


def _to_run_response(run: Run, run_context: RunContext | None = None) -> RunResponse:
    context = None
    if run_context is not None:
        context = RunContextResponse(
            route=run_context.route,
            page_title=run_context.page_title,
            element_hint=run_context.element_hint,
            note=run_context.note,
            metadata=run_context.metadata_json,
        )

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
        context=context,
    )


def _normalize_route_path(route: str) -> str:
    value = route.strip()
    if not value:
        return "/"
    path_only = value.split("?", 1)[0].split("#", 1)[0]
    ensured_prefix = path_only if path_only.startswith("/") else f"/{path_only}"
    if len(ensured_prefix) > 1 and ensured_prefix.endswith("/"):
        return ensured_prefix[:-1]
    return ensured_prefix or "/"


def _get_run_or_404(db: Session, run_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _transition_or_409(
    run: Run,
    *,
    target_state: RunState,
    failure_reason_code: FailureReasonCode | None = None,
) -> tuple[str, str]:
    current_state = RunState(run.status)
    try:
        ensure_transition_allowed(current_state, target_state, failure_reason_code)
    except TransitionRuleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    run.status = target_state.value
    return current_state.value, target_state.value


def _latest_failure_reason_code(db: Session, run_id: str) -> str | None:
    row = (
        db.query(RunEvent)
        .filter(
            RunEvent.run_id == run_id,
            RunEvent.event_type == "status_transition",
            RunEvent.status_to.in_([RunState.FAILED.value, RunState.EXPIRED.value]),
        )
        .order_by(RunEvent.created_at.desc(), RunEvent.id.desc())
        .first()
    )
    if row is None:
        return None

    payload = row.payload if isinstance(row.payload, dict) else {}
    reason = payload.get("failure_reason_code")
    if isinstance(reason, str) and reason:
        return reason

    fallback = payload.get("reason")
    if isinstance(fallback, str) and fallback:
        return fallback
    return None


def _create_child_run_from_parent(
    db: Session,
    *,
    parent_run: Run,
    event_type: str,
    event_payload: dict[str, Any],
    audit_action: str,
) -> tuple[Run, RunContext]:
    parent_context = db.query(RunContext).filter(RunContext.run_id == parent_run.id).first()

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

    child_context = RunContext(
        run_id=child_run.id,
        route=parent_context.route if parent_context else parent_run.route,
        page_title=parent_context.page_title if parent_context else None,
        element_hint=parent_context.element_hint if parent_context else None,
        note=parent_context.note if parent_context else None,
        metadata_json=parent_context.metadata_json if parent_context else None,
    )
    db.add(child_context)

    append_run_event(
        db,
        run_id=child_run.id,
        event_type=event_type,
        status_to=RunState.QUEUED.value,
        payload=event_payload,
        actor_id=parent_run.created_by,
        audit_action=audit_action,
    )
    return child_run, child_context


@router.get("/contract")
def run_contract() -> dict[str, Any]:
    return {
        "states": list_run_states(),
        "failure_reason_codes": list_failure_reason_codes(),
        "recoverable_timeout_reason_codes": sorted(RECOVERABLE_TIMEOUT_REASONS),
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

    run_context = RunContext(
        run_id=run.id,
        route=payload.route,
        page_title=payload.page_title,
        element_hint=payload.element_hint,
        note=payload.note,
        metadata_json=payload.metadata,
    )
    db.add(run_context)

    append_run_event(
        db,
        run_id=run.id,
        event_type="run_created",
        status_to=RunState.QUEUED.value,
        payload={
            "source": "api",
            "context": {
                "route": payload.route,
                "note": payload.note,
                "metadata": payload.metadata,
            },
        },
        actor_id=payload.created_by,
        audit_action="run.prompt.submitted",
    )

    db.commit()
    db.refresh(run)
    db.refresh(run_context)
    return _to_run_response(run, run_context)


@router.get("", response_model=RunListResponse)
def list_runs(
    status: list[str] | None = Query(default=None),
    route: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
) -> RunListResponse:
    query = db.query(Run)
    if status:
        query = query.filter(Run.status.in_(status))
    if route and route.strip():
        normalized_route = _normalize_route_path(route)
        query = query.filter(
            or_(
                Run.route == normalized_route,
                Run.route.like(f"{normalized_route}/%"),
                literal(normalized_route).like(Run.route + "/%"),
            )
        )

    total = query.count()
    runs = query.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()
    run_ids = [run.id for run in runs]

    contexts = (
        db.query(RunContext)
        .filter(RunContext.run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    context_by_run_id = {item.run_id: item for item in contexts}

    return RunListResponse(
        items=[_to_run_response(run, context_by_run_id.get(run.id)) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    run = _get_run_or_404(db, run_id)
    run_context = db.query(RunContext).filter(RunContext.run_id == run.id).first()
    return _to_run_response(run, run_context)


@router.post("/{run_id}/transition", response_model=RunResponse)
def transition_run(
    run_id: str,
    payload: TransitionRunRequest,
    db: Session = Depends(get_db_session),
) -> RunResponse:
    run = _get_run_or_404(db, run_id)
    status_from, status_to = _transition_or_409(
        run,
        target_state=payload.to_status,
        failure_reason_code=payload.failure_reason_code,
    )

    event_payload: dict[str, Any] = {}
    if payload.failure_reason_code is not None:
        event_payload["failure_reason_code"] = payload.failure_reason_code.value

    append_run_event(
        db,
        run_id=run.id,
        event_type="status_transition",
        status_from=status_from,
        status_to=status_to,
        payload=event_payload or None,
    )

    db.commit()
    db.refresh(run)
    run_context = db.query(RunContext).filter(RunContext.run_id == run.id).first()
    return _to_run_response(run, run_context)


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    run = _get_run_or_404(db, run_id)
    status_from, status_to = _transition_or_409(run, target_state=RunState.CANCELED)

    cleanup_result: dict[str, Any]
    lease_release_result: dict[str, Any]
    if run.slot_id:
        slot_id = run.slot_id
        try:
            cleanup_result = cleanup_worktree(db=db, slot_id=slot_id, run_id=run.id)
        except ValueError as exc:
            cleanup_result = {"cleaned": False, "slot_id": slot_id, "run_id": run.id, "reason": str(exc)}
        lease_release_result = release_slot_lease(db=db, slot_id=slot_id, run_id=run.id)
    else:
        cleanup_result = {
            "cleaned": False,
            "slot_id": None,
            "run_id": run.id,
            "reason": "run_slot_not_assigned",
        }
        lease_release_result = {
            "released": False,
            "slot_id": None,
            "run_id": run.id,
            "reason": "run_slot_not_assigned",
        }

    append_run_event(
        db,
        run_id=run.id,
        event_type="status_transition",
        status_from=status_from,
        status_to=status_to,
        payload={
            "source": "cancel_endpoint",
            "resource_cleanup": cleanup_result,
            "lease_release": lease_release_result,
        },
        actor_id=run.created_by,
        audit_action="run.cancel.requested",
    )

    db.commit()
    db.refresh(run)
    run_context = db.query(RunContext).filter(RunContext.run_id == run.id).first()
    return _to_run_response(run, run_context)


@router.post("/{run_id}/retry", response_model=RunResponse)
def retry_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    parent_run = _get_run_or_404(db, run_id)
    child_run, child_context = _create_child_run_from_parent(
        db,
        parent_run=parent_run,
        event_type="run_retried",
        event_payload={"parent_run_id": parent_run.id},
        audit_action="run.prompt.retry",
    )

    db.commit()
    db.refresh(child_run)
    db.refresh(child_context)
    return _to_run_response(child_run, child_context)


@router.post("/{run_id}/resume", response_model=RunResponse)
def resume_run(run_id: str, db: Session = Depends(get_db_session)) -> RunResponse:
    parent_run = _get_run_or_404(db, run_id)
    if parent_run.status not in {RunState.FAILED.value, RunState.EXPIRED.value}:
        raise HTTPException(status_code=409, detail="resume_requires_failed_or_expired_run")

    failure_reason_code = _latest_failure_reason_code(db, parent_run.id)
    if failure_reason_code not in RECOVERABLE_TIMEOUT_REASONS:
        raise HTTPException(
            status_code=409,
            detail=f"resume_not_supported_for_reason:{failure_reason_code or 'unknown'}",
        )

    child_run, child_context = _create_child_run_from_parent(
        db,
        parent_run=parent_run,
        event_type="run_resumed",
        event_payload={
            "parent_run_id": parent_run.id,
            "recovery_reason_code": failure_reason_code,
            "recovery_strategy": "create_child_run",
        },
        audit_action="run.timeout.resumed",
    )

    db.commit()
    db.refresh(child_run)
    db.refresh(child_context)
    return _to_run_response(child_run, child_context)
