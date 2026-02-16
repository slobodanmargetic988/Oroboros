from __future__ import annotations

from datetime import datetime
import json
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db_session
from app.models import Run, RunEvent
from app.services.run_event_log import EVENT_SCHEMA_VERSION, event_schema_version

router = APIRouter(prefix="/api", tags=["events"])


class RunEventResponse(BaseModel):
    schema_version: int
    id: int
    run_id: str
    event_type: str
    status_from: str | None
    status_to: str | None
    payload: dict[str, Any] | None
    created_at: datetime


def _to_response(event: RunEvent) -> RunEventResponse:
    payload = dict(event.payload) if isinstance(event.payload, dict) else event.payload
    if isinstance(payload, dict):
        payload.setdefault("schema_version", event_schema_version(payload))
    return RunEventResponse(
        schema_version=event_schema_version(event.payload),
        id=event.id,
        run_id=event.run_id,
        event_type=event.event_type,
        status_from=event.status_from,
        status_to=event.status_to,
        payload=payload,
        created_at=event.created_at,
    )


def _fetch_events(
    db: Session,
    *,
    run_id: str,
    limit: int,
    since_id: int | None = None,
    order: Literal["asc", "desc"] = "asc",
) -> list[RunEvent]:
    query = db.query(RunEvent).filter(RunEvent.run_id == run_id)
    if since_id is not None:
        query = query.filter(RunEvent.id > since_id)
    if order == "desc":
        return query.order_by(RunEvent.created_at.desc(), RunEvent.id.desc()).limit(limit).all()
    return query.order_by(RunEvent.created_at.asc(), RunEvent.id.asc()).limit(limit).all()


@router.get("/events/schema")
def get_events_schema() -> dict[str, Any]:
    return {
        "version": EVENT_SCHEMA_VERSION,
        "event_fields": [
            "schema_version",
            "id",
            "run_id",
            "event_type",
            "status_from",
            "status_to",
            "payload",
            "created_at",
        ],
        "stream": {
            "path": "/api/runs/{run_id}/events/stream",
            "protocol": "sse",
            "event_name": "run_event",
            "cursor_param": "since_id",
        },
    }


@router.get("/runs/{run_id}/events", response_model=list[RunEventResponse])
def list_run_events(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    order: Literal["asc", "desc"] = Query(default="asc"),
    db: Session = Depends(get_db_session),
) -> list[RunEventResponse]:
    events = _fetch_events(db, run_id=run_id, limit=limit, order=order)
    return [_to_response(event) for event in events]


@router.get("/runs/{run_id}/events/stream")
def stream_run_events(
    run_id: str,
    since_id: int | None = Query(default=None, ge=0),
    follow: bool = Query(default=True),
    poll_interval_seconds: float = Query(default=0.75, ge=0.1, le=10.0),
    heartbeat_seconds: int = Query(default=15, ge=5, le=120),
    batch_limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    run_exists = db.query(Run.id).filter(Run.id == run_id).first()
    if run_exists is None:
        raise HTTPException(status_code=404, detail="Run not found")

    def event_stream():
        cursor = since_id
        heartbeat_deadline = time.monotonic() + heartbeat_seconds
        while True:
            with SessionLocal() as stream_db:
                events = _fetch_events(stream_db, run_id=run_id, since_id=cursor, limit=batch_limit)

            if events:
                for row in events:
                    response = _to_response(row)
                    body = json.dumps(response.model_dump(mode="json"))
                    yield f"id: {row.id}\nevent: run_event\ndata: {body}\n\n"
                    cursor = row.id
                heartbeat_deadline = time.monotonic() + heartbeat_seconds
                if not follow:
                    return
                continue

            if not follow:
                return

            if time.monotonic() >= heartbeat_deadline:
                yield ": heartbeat\n\n"
                heartbeat_deadline = time.monotonic() + heartbeat_seconds

            time.sleep(poll_interval_seconds)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
