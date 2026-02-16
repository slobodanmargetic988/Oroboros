from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import uuid


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_trace_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:128]


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def emit_worker_log(
    *,
    event: str,
    level: int = logging.INFO,
    trace_id: str | None = None,
    run_id: str | None = None,
    slot_id: str | None = None,
    commit_sha: str | None = None,
    **fields,
) -> None:
    payload: dict[str, object | None] = {
        "timestamp_utc": _utcnow_iso(),
        "component": "worker",
        "event": event,
        "trace_id": normalize_trace_id(trace_id),
        "run_id": run_id,
        "slot_id": slot_id,
        "commit_sha": commit_sha,
    }
    payload.update(fields)
    logging.getLogger("worker").log(level, json.dumps(payload, sort_keys=True, default=str))
