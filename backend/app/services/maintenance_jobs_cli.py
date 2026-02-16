from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import PreviewDbReset, Release, SlotLease
from app.services.slot_lease_manager import reap_expired_slot_leases


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _serialize_datetime(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


@dataclass
class PreviewResetAuditResult:
    status: str
    counts: dict[str, int]
    issues: list[str]
    latest_by_slot: list[dict[str, Any]]
    window_start: datetime
    generated_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "job": "preview_reset_integrity_audit",
            "status": self.status,
            "generated_at": _serialize_datetime(self.generated_at),
            "window_start": _serialize_datetime(self.window_start),
            "counts": self.counts,
            "issues": self.issues,
            "latest_by_slot": self.latest_by_slot,
        }


def _audit_preview_reset_integrity(
    *,
    db: Session,
    lookback_hours: int,
    running_grace_minutes: int,
) -> PreviewResetAuditResult:
    generated_at = _utcnow()
    window_start = generated_at - timedelta(hours=max(1, lookback_hours))
    running_stale_before = generated_at - timedelta(minutes=max(1, running_grace_minutes))

    records = (
        db.query(PreviewDbReset)
        .filter(PreviewDbReset.reset_started_at >= window_start)
        .order_by(PreviewDbReset.reset_started_at.desc(), PreviewDbReset.id.desc())
        .all()
    )

    counts = {
        "total": len(records),
        "completed": 0,
        "failed": 0,
        "running": 0,
        "running_stale": 0,
        "completed_missing_completed_at": 0,
        "completed_missing_details": 0,
    }
    issues: list[str] = []

    latest_by_slot: list[dict[str, Any]] = []
    seen_slots: set[str] = set()

    for record in records:
        status = (record.reset_status or "unknown").lower()
        if status == "completed":
            counts["completed"] += 1
        elif status in {"failed", "error"}:
            counts["failed"] += 1
        elif status == "running":
            counts["running"] += 1

        if status == "running" and _as_utc(record.reset_started_at) <= running_stale_before:
            counts["running_stale"] += 1

        if status == "completed" and record.reset_completed_at is None:
            counts["completed_missing_completed_at"] += 1

        if status == "completed" and record.details_json is None:
            counts["completed_missing_details"] += 1

        if record.slot_id not in seen_slots:
            seen_slots.add(record.slot_id)
            latest_by_slot.append(
                {
                    "slot_id": record.slot_id,
                    "run_id": record.run_id,
                    "status": record.reset_status,
                    "started_at": _serialize_datetime(record.reset_started_at),
                    "completed_at": _serialize_datetime(record.reset_completed_at),
                    "strategy": record.strategy,
                    "seed_version": record.seed_version,
                    "snapshot_version": record.snapshot_version,
                }
            )

    if counts["total"] == 0:
        status = "no_data"
        issues.append("No preview reset records in lookback window.")
    else:
        status = "passed"
        if counts["failed"] > 0:
            status = "failed"
            issues.append(f"Detected {counts['failed']} failed preview reset records.")
        if counts["running_stale"] > 0:
            status = "failed"
            issues.append(
                f"Detected {counts['running_stale']} stale running reset records older than {running_grace_minutes} minutes."
            )
        if counts["completed_missing_completed_at"] > 0:
            status = "failed"
            issues.append(
                f"Detected {counts['completed_missing_completed_at']} completed resets missing reset_completed_at."
            )
        if counts["completed_missing_details"] > 0:
            status = "failed"
            issues.append(
                f"Detected {counts['completed_missing_details']} completed resets missing details_json."
            )

    return PreviewResetAuditResult(
        status=status,
        counts=counts,
        issues=issues,
        latest_by_slot=latest_by_slot,
        window_start=window_start,
        generated_at=generated_at,
    )


def _run_stale_lease_cleanup(db: Session) -> dict[str, Any]:
    result = reap_expired_slot_leases(db=db)
    db.commit()
    return {
        "job": "stale_lease_cleanup",
        "generated_at": _serialize_datetime(_utcnow()),
        "expired_count": int(result.get("expired_count", 0)),
        "expired_slots": result.get("expired_slots", []),
    }


def _run_preview_reset_integrity(
    db: Session,
    *,
    lookback_hours: int,
    running_grace_minutes: int,
) -> tuple[dict[str, Any], int]:
    audit = _audit_preview_reset_integrity(
        db=db,
        lookback_hours=lookback_hours,
        running_grace_minutes=running_grace_minutes,
    )
    payload = audit.to_payload()
    exit_code = 0 if audit.status in {"passed", "no_data"} else 2
    return payload, exit_code


def _runtime_health_payload(runtime_health_cmd: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["bash", "-lc", runtime_health_cmd],
        check=False,
        capture_output=True,
        text=True,
    )
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    stderr_lines = [line for line in completed.stderr.splitlines() if line.strip()]
    return {
        "command": runtime_health_cmd,
        "exit_code": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout_tail": stdout_lines[-20:],
        "stderr_tail": stderr_lines[-20:],
    }


def _release_summary_payload(db: Session, *, release_limit: int) -> dict[str, Any]:
    releases = db.query(Release).order_by(Release.id.desc()).limit(max(1, release_limit)).all()
    status_counts = dict(Counter(item.status for item in releases))

    latest = releases[0] if releases else None
    latest_deployed = next((item for item in releases if item.status in {"deployed", "rolled_back"}), None)

    return {
        "limit": max(1, release_limit),
        "count": len(releases),
        "status_counts": status_counts,
        "latest": {
            "release_id": latest.release_id,
            "commit_sha": latest.commit_sha,
            "status": latest.status,
            "deployed_at": _serialize_datetime(latest.deployed_at),
        }
        if latest
        else None,
        "latest_deployed": {
            "release_id": latest_deployed.release_id,
            "commit_sha": latest_deployed.commit_sha,
            "status": latest_deployed.status,
            "deployed_at": _serialize_datetime(latest_deployed.deployed_at),
        }
        if latest_deployed
        else None,
    }


def _slot_lease_summary_payload(db: Session) -> dict[str, Any]:
    settings = get_settings()
    configured_slots = [part.strip() for part in settings.slot_ids_csv.split(",") if part.strip()] or [
        "preview-1",
        "preview-2",
        "preview-3",
    ]
    now = _utcnow()
    leases = db.query(SlotLease).filter(SlotLease.slot_id.in_(configured_slots)).all()
    lease_map = {lease.slot_id: lease for lease in leases}

    states: list[dict[str, Any]] = []
    for slot_id in configured_slots:
        lease = lease_map.get(slot_id)
        if lease is None:
            states.append({"slot_id": slot_id, "state": "available", "run_id": None})
            continue

        expires_at = _as_utc(lease.expires_at)
        effective_state = lease.lease_state
        if lease.lease_state == "leased" and expires_at <= now:
            effective_state = "expired"

        states.append(
            {
                "slot_id": slot_id,
                "state": effective_state,
                "run_id": lease.run_id,
                "expires_at": _serialize_datetime(lease.expires_at),
            }
        )

    state_counts = dict(Counter(item["state"] for item in states))
    state_counts.setdefault("available", 0)

    return {
        "configured_slots": configured_slots,
        "state_counts": state_counts,
        "states": states,
    }


def _run_daily_health_summary(
    db: Session,
    *,
    output_dir: str,
    runtime_health_cmd: str,
    release_limit: int,
    lookback_hours: int,
    running_grace_minutes: int,
) -> tuple[dict[str, Any], int]:
    generated_at = _utcnow()

    runtime_health = _runtime_health_payload(runtime_health_cmd)
    preview_audit = _audit_preview_reset_integrity(
        db=db,
        lookback_hours=lookback_hours,
        running_grace_minutes=running_grace_minutes,
    ).to_payload()

    releases = _release_summary_payload(db=db, release_limit=release_limit)
    leases = _slot_lease_summary_payload(db=db)

    overall_status = "passed"
    if not runtime_health["ok"]:
        overall_status = "failed"
    if preview_audit["status"] == "failed":
        overall_status = "failed"

    payload = {
        "job": "daily_health_summary",
        "generated_at": _serialize_datetime(generated_at),
        "overall_status": overall_status,
        "runtime_health": runtime_health,
        "preview_reset_integrity": preview_audit,
        "release_summary": releases,
        "slot_lease_summary": leases,
    }

    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"daily-health-summary-{generated_at.strftime('%Y%m%d')}.json"
    target_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload["summary_file"] = str(target_file)
    exit_code = 0 if overall_status == "passed" else 2
    return payload, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run host-native maintenance jobs for Ouroboros runtime")
    subparsers = parser.add_subparsers(dest="job", required=True)

    subparsers.add_parser("stale-lease-cleanup")

    reset_integrity_parser = subparsers.add_parser("preview-reset-integrity")
    reset_integrity_parser.add_argument("--lookback-hours", type=int, default=24)
    reset_integrity_parser.add_argument("--running-grace-minutes", type=int, default=90)

    default_runtime_health_cmd = str((_project_root() / "scripts" / "runtime-health-check.sh").resolve())
    daily_summary_parser = subparsers.add_parser("daily-health-summary")
    daily_summary_parser.add_argument("--output-dir", default="/srv/oroboros/artifacts/maintenance")
    daily_summary_parser.add_argument("--runtime-health-cmd", default=default_runtime_health_cmd)
    daily_summary_parser.add_argument("--release-limit", type=int, default=20)
    daily_summary_parser.add_argument("--lookback-hours", type=int, default=24)
    daily_summary_parser.add_argument("--running-grace-minutes", type=int, default=90)

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.job == "stale-lease-cleanup":
            payload = _run_stale_lease_cleanup(db)
            _print_payload(payload)
            return 0

        if args.job == "preview-reset-integrity":
            payload, exit_code = _run_preview_reset_integrity(
                db,
                lookback_hours=args.lookback_hours,
                running_grace_minutes=args.running_grace_minutes,
            )
            _print_payload(payload)
            return exit_code

        if args.job == "daily-health-summary":
            payload, exit_code = _run_daily_health_summary(
                db,
                output_dir=args.output_dir,
                runtime_health_cmd=args.runtime_health_cmd,
                release_limit=args.release_limit,
                lookback_hours=args.lookback_hours,
                running_grace_minutes=args.running_grace_minutes,
            )
            _print_payload(payload)
            return exit_code

        _print_payload({"error": "unsupported_job", "job": args.job})
        return 1
    except Exception as exc:
        db.rollback()
        _print_payload(
            {
                "error": "maintenance_job_failed",
                "job": getattr(args, "job", "unknown"),
                "detail": str(exc),
                "generated_at": _serialize_datetime(_utcnow()),
            }
        )
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
