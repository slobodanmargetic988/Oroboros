from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import PreviewDbReset, Run, RunEvent, SlotLease
from app.models.common import utcnow
from app.services.preview_db_reset import db_name_for_slot, normalize_slot, reset_and_seed_slot

SLOT_ORDER = ["preview1", "preview2", "preview3"]


class SlotUnavailableError(RuntimeError):
    """Raised when no preview slot is available."""


@dataclass
class SlotAllocationResult:
    run_id: str
    slot_id: str
    db_name: str
    seed_version: str
    snapshot_version: str | None
    strategy: str
    dry_run: bool


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _active_slots(db: Session, now: datetime) -> set[str]:
    leases = (
        db.query(SlotLease)
        .filter(SlotLease.lease_state == "active")
        .all()
    )
    active: set[str] = set()
    for lease in leases:
        expires_at = _as_utc(lease.expires_at)
        if expires_at > now:
            active.add(normalize_slot(lease.slot_id))
        else:
            lease.lease_state = "expired"
    return active


def allocate_slot_for_run(
    *,
    db: Session,
    run_id: str,
    seed_version: str = "v1",
    strategy: str = "seed",
    snapshot_version: str | None = None,
    lease_ttl_minutes: int = 30,
    dry_run: bool = False,
) -> SlotAllocationResult:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError(f"Run '{run_id}' not found")

    now = datetime.now(timezone.utc)
    active = _active_slots(db, now)

    available_slot = next((slot for slot in SLOT_ORDER if slot not in active), None)
    if available_slot is None:
        raise SlotUnavailableError("No preview slot available")

    reset_started_at = utcnow()
    reset_record = PreviewDbReset(
        run_id=run_id,
        slot_id=available_slot,
        db_name=db_name_for_slot(available_slot),
        strategy=strategy,
        seed_version=seed_version,
        snapshot_version=snapshot_version,
        reset_status="running",
        reset_started_at=reset_started_at,
    )
    db.add(reset_record)
    db.flush()

    try:
        reset_details = reset_and_seed_slot(
            slot_id=available_slot,
            run_id=run_id,
            seed_version=seed_version,
            strategy=strategy,
            snapshot_version=snapshot_version,
            dry_run=dry_run,
        )
    except Exception as exc:
        reset_record.reset_status = "failed"
        reset_record.reset_completed_at = utcnow()
        reset_record.details_json = {"error": str(exc)}
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="preview_reset_failed",
                status_from=run.status,
                status_to=run.status,
                payload={"slot_id": available_slot, "error": str(exc)},
            )
        )
        db.commit()
        raise

    lease = db.query(SlotLease).filter(SlotLease.slot_id == available_slot).first()
    if lease is None:
        lease = SlotLease(
            slot_id=available_slot,
            run_id=run.id,
            lease_state="active",
            leased_at=now,
            expires_at=now + timedelta(minutes=lease_ttl_minutes),
            heartbeat_at=now,
        )
        db.add(lease)
    else:
        lease.run_id = run.id
        lease.lease_state = "active"
        lease.leased_at = now
        lease.expires_at = now + timedelta(minutes=lease_ttl_minutes)
        lease.heartbeat_at = now

    run.slot_id = available_slot

    reset_record.reset_status = "completed"
    reset_record.reset_completed_at = utcnow()
    reset_record.details_json = dict(reset_details)

    db.add(
        RunEvent(
            run_id=run.id,
            event_type="preview_slot_allocated",
            status_from=run.status,
            status_to=run.status,
            payload={
                "slot_id": available_slot,
                "seed_version": seed_version,
                "snapshot_version": snapshot_version,
                "strategy": strategy,
            },
        )
    )

    db.commit()

    return SlotAllocationResult(
        run_id=run.id,
        slot_id=available_slot,
        db_name=db_name_for_slot(available_slot),
        seed_version=seed_version,
        snapshot_version=snapshot_version,
        strategy=strategy,
        dry_run=dry_run,
    )
