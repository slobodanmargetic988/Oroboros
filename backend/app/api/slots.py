from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.slot_lease_manager import (
    WAITING_FOR_SLOT_REASON,
    acquire_slot_lease,
    heartbeat_slot_lease,
    list_slot_states,
    reap_expired_slot_leases,
    release_slot_lease,
)

router = APIRouter(prefix="/api/slots", tags=["slots"])


class AcquireSlotRequest(BaseModel):
    run_id: str


class AcquireSlotResponse(BaseModel):
    acquired: bool
    slot_id: str | None
    queue_reason: str | None
    expires_at: datetime | None
    ttl_seconds: int


class ReleaseSlotRequest(BaseModel):
    run_id: str | None = None


class ReleaseSlotResponse(BaseModel):
    released: bool
    slot_id: str
    run_id: str | None
    reason: str | None


class HeartbeatSlotRequest(BaseModel):
    run_id: str


class HeartbeatSlotResponse(BaseModel):
    heartbeat_updated: bool
    slot_id: str
    run_id: str
    reason: str | None
    expires_at: datetime | None


class ReapExpiredResponse(BaseModel):
    expired_count: int
    expired_slots: list[str]


class SlotStateResponse(BaseModel):
    slot_id: str
    state: str
    run_id: str | None
    lease_state: str | None
    expires_at: datetime | None
    heartbeat_at: datetime | None


@router.get("", response_model=list[SlotStateResponse])
def get_slots(db: Session = Depends(get_db_session)) -> list[SlotStateResponse]:
    rows = list_slot_states(db)
    return [SlotStateResponse(**row) for row in rows]


@router.post("/acquire", response_model=AcquireSlotResponse)
def acquire_slot(payload: AcquireSlotRequest, db: Session = Depends(get_db_session)) -> AcquireSlotResponse:
    try:
        result = acquire_slot_lease(db=db, run_id=payload.run_id)
        db.commit()
        return AcquireSlotResponse(**result)
    except ValueError as exc:
        db.rollback()
        if str(exc) == "run_not_found":
            raise HTTPException(status_code=404, detail="Run not found") from exc
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/{slot_id}/release", response_model=ReleaseSlotResponse)
def release_slot(
    slot_id: str,
    payload: ReleaseSlotRequest,
    db: Session = Depends(get_db_session),
) -> ReleaseSlotResponse:
    try:
        result = release_slot_lease(db=db, slot_id=slot_id, run_id=payload.run_id)
        db.commit()
        return ReleaseSlotResponse(**result)
    except Exception:
        db.rollback()
        raise


@router.post("/{slot_id}/heartbeat", response_model=HeartbeatSlotResponse)
def heartbeat_slot(
    slot_id: str,
    payload: HeartbeatSlotRequest,
    db: Session = Depends(get_db_session),
) -> HeartbeatSlotResponse:
    try:
        result = heartbeat_slot_lease(db=db, slot_id=slot_id, run_id=payload.run_id)
        db.commit()
        return HeartbeatSlotResponse(**result)
    except Exception:
        db.rollback()
        raise


@router.post("/reap-expired", response_model=ReapExpiredResponse)
def reap_expired(db: Session = Depends(get_db_session)) -> ReapExpiredResponse:
    try:
        result = reap_expired_slot_leases(db=db)
        db.commit()
        return ReapExpiredResponse(**result)
    except Exception:
        db.rollback()
        raise


@router.get("/contract")
def slot_contract() -> dict[str, object]:
    return {
        "acquire_behavior": {
            "all_slots_occupied": {
                "acquired": False,
                "queue_reason": WAITING_FOR_SLOT_REASON,
                "queue_behavior": "run_kept_queued_while_waiting_for_slot",
            }
        },
        "slot_ids": ["preview-1", "preview-2", "preview-3"],
    }
