from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, RunEvent

EVENT_SCHEMA_VERSION = 1


def normalize_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(payload or {})
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, int) or schema_version <= 0:
        value["schema_version"] = EVENT_SCHEMA_VERSION
    return value


def event_schema_version(payload: dict[str, Any] | None) -> int:
    schema_version = (payload or {}).get("schema_version")
    if isinstance(schema_version, int) and schema_version > 0:
        return schema_version
    return EVENT_SCHEMA_VERSION


def _payload_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append_audit_log(
    db: Session,
    *,
    action: str,
    payload: dict[str, Any],
    actor_id: str | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        payload_hash=_payload_hash(payload),
        payload_json=payload,
    )
    db.add(row)
    return row


def append_run_event(
    db: Session,
    *,
    run_id: str,
    event_type: str,
    status_from: str | None = None,
    status_to: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    audit_action: str | None = None,
    audit_payload: dict[str, Any] | None = None,
) -> RunEvent:
    normalized_payload = normalize_event_payload(payload)
    row = RunEvent(
        run_id=run_id,
        event_type=event_type,
        status_from=status_from,
        status_to=status_to,
        payload=normalized_payload,
    )
    db.add(row)

    if audit_action:
        event_audit_payload = dict(audit_payload or {})
        event_audit_payload.setdefault("schema_version", event_schema_version(normalized_payload))
        event_audit_payload.setdefault("run_id", run_id)
        event_audit_payload.setdefault("event_type", event_type)
        event_audit_payload.setdefault("status_from", status_from)
        event_audit_payload.setdefault("status_to", status_to)
        event_audit_payload.setdefault("payload", normalized_payload)
        append_audit_log(
            db,
            action=audit_action,
            payload=event_audit_payload,
            actor_id=actor_id,
        )

    return row
