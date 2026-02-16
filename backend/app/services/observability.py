from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import json
import logging
import uuid


_TRACE_ID_CONTEXT: ContextVar[str | None] = ContextVar("trace_id", default=None)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_trace_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 128:
        return normalized[:128]
    return normalized


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def ensure_trace_id(value: str | None) -> str:
    normalized = normalize_trace_id(value)
    if normalized:
        return normalized
    return generate_trace_id()


def current_trace_id() -> str | None:
    return _TRACE_ID_CONTEXT.get()


def set_current_trace_id(trace_id: str | None) -> Token[str | None]:
    return _TRACE_ID_CONTEXT.set(normalize_trace_id(trace_id))


def reset_current_trace_id(token: Token[str | None]) -> None:
    _TRACE_ID_CONTEXT.reset(token)


def extract_trace_id_from_metadata(metadata: dict | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("trace_id")
    if not isinstance(value, str):
        return None
    return normalize_trace_id(value)


def emit_structured_log(
    *,
    component: str,
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
        "component": component,
        "event": event,
        "trace_id": normalize_trace_id(trace_id) or current_trace_id(),
        "run_id": run_id,
        "slot_id": slot_id,
        "commit_sha": commit_sha,
    }
    payload.update(fields)
    logging.getLogger(component).log(level, json.dumps(payload, sort_keys=True, default=str))
