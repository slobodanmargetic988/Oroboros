from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Run, RunArtifact
from app.services.run_event_log import append_run_event


DEFAULT_SLOT_HOST_MAP = {
    "preview-1": "preview1.example.com",
    "preview-2": "preview2.example.com",
    "preview-3": "preview3.example.com",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_slot_host_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return dict(DEFAULT_SLOT_HOST_MAP)

    parsed: dict[str, str] = {}
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"invalid_slot_host_map_token:{token}")
        slot_id, host = token.split("=", 1)
        slot_key = slot_id.strip()
        host_value = host.strip()
        if not slot_key or not host_value:
            raise ValueError(f"invalid_slot_host_map_token:{token}")
        parsed[slot_key] = host_value

    if not parsed:
        raise ValueError("empty_slot_host_map")
    return parsed


def resolve_preview_host(slot_id: str | None, slot_host_map: dict[str, str]) -> str:
    if slot_id and slot_id in slot_host_map:
        return slot_host_map[slot_id]
    first = next(iter(slot_host_map.values()), None)
    if not first:
        raise ValueError("preview_host_map_empty")
    return first


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path(f"/tmp/integration-happy-path-{stamp}.json")


def persist_happy_path_report_for_run(
    *,
    db: Session,
    run_id: str,
    report: dict[str, Any],
    artifact_uri: str,
) -> None:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError("run_not_found")

    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    overall_status = str(summary.get("overall_status", "failed"))
    health_status = (
        report.get("post_deploy_health", {}).get("status")
        if isinstance(report.get("post_deploy_health"), dict)
        else None
    )

    db.add(
        RunArtifact(
            run_id=run_id,
            artifact_type="integration_happy_path_report",
            artifact_uri=artifact_uri,
            metadata_json={
                "overall_status": overall_status,
                "post_deploy_health_status": health_status,
                "event_count": int(report.get("events_count", 0)),
            },
        )
    )
    append_run_event(
        db,
        run_id=run_id,
        event_type="integration_happy_path_completed",
        status_from=run.status,
        status_to=run.status,
        payload={
            "overall_status": overall_status,
            "artifact_uri": artifact_uri,
            "post_deploy_health_status": health_status,
        },
        actor_id=None,
        audit_action="run.integration.happy_path",
    )
    db.commit()
