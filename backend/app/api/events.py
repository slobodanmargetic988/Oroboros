from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models import RunEvent

router = APIRouter(prefix="/api", tags=["events"])


class RunEventResponse(BaseModel):
    id: int
    run_id: str
    event_type: str
    status_from: str | None
    status_to: str | None
    payload: dict[str, Any] | None
    created_at: datetime


@router.get("/runs/{run_id}/events", response_model=list[RunEventResponse])
def list_run_events(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> list[RunEventResponse]:
    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.created_at.asc(), RunEvent.id.asc())
        .limit(limit)
        .all()
    )

    return [
        RunEventResponse(
            id=event.id,
            run_id=event.run_id,
            event_type=event.event_type,
            status_from=event.status_from,
            status_to=event.status_to,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.get("/runs/{run_id}/events/stream")
def stream_run_events_stub(run_id: str) -> dict[str, str]:
    return {
        "run_id": run_id,
        "status": "not_implemented",
        "detail": "SSE/WebSocket stream skeleton reserved for MYO-17 contract.",
    }
