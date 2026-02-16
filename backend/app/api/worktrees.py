from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.git_worktree_manager import (
    BRANCH_PREFIX,
    assign_worktree,
    cleanup_worktree,
    list_worktree_bindings,
)

router = APIRouter(prefix="/api/worktrees", tags=["worktrees"])


class AssignWorktreeRequest(BaseModel):
    run_id: str
    slot_id: str


class AssignWorktreeResponse(BaseModel):
    assigned: bool
    reused: bool
    slot_id: str
    run_id: str
    branch_name: str
    worktree_path: str


class CleanupWorktreeRequest(BaseModel):
    run_id: str | None = None


class CleanupWorktreeResponse(BaseModel):
    cleaned: bool
    slot_id: str
    run_id: str | None
    branch_name: str | None = None
    worktree_path: str | None = None
    reason: str | None


class WorktreeBindingResponse(BaseModel):
    slot_id: str
    state: str
    run_id: str | None
    branch_name: str | None
    worktree_path: str | None
    binding_state: str | None
    last_action: str | None
    updated_at: datetime | None


def _value_error_to_http(exc: ValueError) -> HTTPException:
    message = str(exc)
    if message == "run_not_found":
        return HTTPException(status_code=404, detail="Run not found")
    if message in {"invalid_slot_id", "invalid_run_id_for_branch"}:
        return HTTPException(status_code=422, detail=message)
    if message in {"active_lease_required", "slot_bound_to_other_run", "run_bound_to_other_slot"}:
        return HTTPException(status_code=409, detail=message)
    if message in {"branch_name_conflict"}:
        return HTTPException(status_code=409, detail=message)
    if message in {"repo_root_not_found", "worktree_path_out_of_bounds"}:
        return HTTPException(status_code=500, detail=message)
    if message.startswith("git_command_failed:"):
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=400, detail=message)


@router.get("", response_model=list[WorktreeBindingResponse])
def get_worktree_bindings(db: Session = Depends(get_db_session)) -> list[WorktreeBindingResponse]:
    rows = list_worktree_bindings(db)
    return [WorktreeBindingResponse(**row) for row in rows]


@router.post("/assign", response_model=AssignWorktreeResponse)
def assign_worktree_for_slot(
    payload: AssignWorktreeRequest,
    db: Session = Depends(get_db_session),
) -> AssignWorktreeResponse:
    try:
        result = assign_worktree(db=db, run_id=payload.run_id, slot_id=payload.slot_id)
        db.commit()
        return AssignWorktreeResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise _value_error_to_http(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/{slot_id}/cleanup", response_model=CleanupWorktreeResponse)
def cleanup_slot_worktree(
    slot_id: str,
    payload: CleanupWorktreeRequest,
    db: Session = Depends(get_db_session),
) -> CleanupWorktreeResponse:
    try:
        result = cleanup_worktree(db=db, slot_id=slot_id, run_id=payload.run_id)
        db.commit()
        return CleanupWorktreeResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise _value_error_to_http(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.get("/contract")
def worktree_contract() -> dict[str, Any]:
    return {
        "branch_name_pattern": f"{BRANCH_PREFIX}<run_id>",
        "slot_binding_policy": "one_worktree_per_slot_with_persisted_binding",
        "operations": ["assign", "reuse", "cleanup"],
    }
