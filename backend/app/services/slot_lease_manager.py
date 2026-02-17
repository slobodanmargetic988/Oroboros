from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.run_state_machine import RunState, TransitionRuleError, ensure_transition_allowed
from app.models import Run, RunEvent, SlotLease


WAITING_FOR_SLOT_REASON = "WAITING_FOR_SLOT"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _configured_slot_ids() -> list[str]:
    settings = get_settings()
    raw = getattr(settings, "slot_ids_csv", "preview-1,preview-2,preview-3")
    slot_ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not slot_ids:
        return ["preview-1", "preview-2", "preview-3"]
    return slot_ids


def _lease_ttl_seconds() -> int:
    settings = get_settings()
    ttl = int(getattr(settings, "slot_lease_ttl_seconds", 1800))
    return max(30, ttl)


def _add_run_event(
    db: Session,
    run_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    status_from: str | None = None,
    status_to: str | None = None,
) -> None:
    db.add(
        RunEvent(
            run_id=run_id,
            event_type=event_type,
            status_from=status_from,
            status_to=status_to,
            payload=payload,
        )
    )


def _get_run_or_raise(db: Session, run_id: str) -> Run:
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise ValueError("run_not_found")
    return run


def _load_slot_lease_map(db: Session, slot_ids: list[str]) -> dict[str, SlotLease]:
    leases = (
        db.query(SlotLease)
        .filter(SlotLease.slot_id.in_(slot_ids))
        .with_for_update()
        .all()
    )
    return {lease.slot_id: lease for lease in leases}


def _mark_run_expired_for_slot_ttl(
    db: Session,
    *,
    run: Run,
    slot_id: str,
    source: str,
) -> None:
    try:
        current_state = RunState(run.status)
    except ValueError:
        _add_run_event(
            db,
            run_id=run.id,
            event_type="slot_expiry_transition_skipped",
            payload={
                "slot_id": slot_id,
                "source": source,
                "run_status": run.status,
                "reason": "unknown_run_status",
            },
        )
        return
    if current_state == RunState.EXPIRED:
        return

    try:
        ensure_transition_allowed(current_state, RunState.EXPIRED)
    except TransitionRuleError:
        _add_run_event(
            db,
            run_id=run.id,
            event_type="slot_expiry_transition_skipped",
            payload={
                "slot_id": slot_id,
                "source": source,
                "run_status": run.status,
                "reason": "invalid_transition",
            },
        )
        return

    run.status = RunState.EXPIRED.value
    _add_run_event(
        db,
        run_id=run.id,
        event_type="status_transition",
        status_from=current_state.value,
        status_to=RunState.EXPIRED.value,
        payload={
            "source": source,
            "reason": "PREVIEW_EXPIRED",
            "failure_reason_code": "PREVIEW_EXPIRED",
            "recoverable": True,
            "recovery_strategy": "create_child_run",
            "resume_endpoint": f"/api/runs/{run.id}/resume",
            "slot_id": slot_id,
        },
    )


def _expire_lease_and_link_run(db: Session, *, lease: SlotLease, now: datetime, source: str) -> None:
    lease.lease_state = "expired"
    lease.heartbeat_at = now

    run = db.query(Run).filter(Run.id == lease.run_id).first()
    if run is not None and run.slot_id == lease.slot_id:
        run.slot_id = None
        _mark_run_expired_for_slot_ttl(db, run=run, slot_id=lease.slot_id, source=source)

    _add_run_event(
        db,
        run_id=lease.run_id,
        event_type="slot_expired",
        payload={
            "slot_id": lease.slot_id,
            "reason": "PREVIEW_EXPIRED",
            "source": source,
        },
    )


def acquire_slot_lease(db: Session, run_id: str) -> dict[str, Any]:
    run = _get_run_or_raise(db, run_id)

    now = _utcnow()
    ttl_seconds = _lease_ttl_seconds()
    expiry = now + timedelta(seconds=ttl_seconds)
    slot_ids = _configured_slot_ids()

    lease_map = _load_slot_lease_map(db, slot_ids)

    for lease in lease_map.values():
        lease_expires = _normalize_utc(lease.expires_at)
        if lease.lease_state == "leased" and lease_expires <= now:
            _expire_lease_and_link_run(db, lease=lease, now=now, source="slot_acquire_ttl_reaper")

    # Idempotent acquire if run already has active lease.
    for lease in lease_map.values():
        lease_expires = _normalize_utc(lease.expires_at)
        if lease.run_id == run_id and lease.lease_state == "leased" and lease_expires > now:
            run.slot_id = lease.slot_id
            _add_run_event(
                db,
                run_id=run_id,
                event_type="slot_acquire_idempotent",
                payload={"slot_id": lease.slot_id, "expires_at": lease_expires.isoformat()},
            )
            return {
                "acquired": True,
                "slot_id": lease.slot_id,
                "queue_reason": None,
                "expires_at": lease_expires,
                "ttl_seconds": ttl_seconds,
            }

    occupied_slots: set[str] = set()
    for slot_id, lease in lease_map.items():
        if lease.lease_state != "leased":
            continue
        lease_expires = _normalize_utc(lease.expires_at)
        if lease_expires > now:
            occupied_slots.add(slot_id)

    free_slots = [slot_id for slot_id in slot_ids if slot_id not in occupied_slots]

    if not free_slots:
        _add_run_event(
            db,
            run_id=run_id,
            event_type="slot_waiting",
            payload={
                "reason": WAITING_FOR_SLOT_REASON,
                "occupied_slots": sorted(occupied_slots),
                "queue_behavior": "run_kept_queued_while_waiting_for_slot",
            },
        )
        return {
            "acquired": False,
            "slot_id": None,
            "queue_reason": WAITING_FOR_SLOT_REASON,
            "expires_at": None,
            "ttl_seconds": ttl_seconds,
        }

    selected_slot = free_slots[0]
    existing_lease = lease_map.get(selected_slot)

    if existing_lease is None:
        existing_lease = SlotLease(
            slot_id=selected_slot,
            run_id=run_id,
            lease_state="leased",
            leased_at=now,
            expires_at=expiry,
            heartbeat_at=now,
        )
        db.add(existing_lease)
    else:
        existing_lease.run_id = run_id
        existing_lease.lease_state = "leased"
        existing_lease.leased_at = now
        existing_lease.expires_at = expiry
        existing_lease.heartbeat_at = now

    run.slot_id = selected_slot

    _add_run_event(
        db,
        run_id=run_id,
        event_type="slot_acquired",
        payload={"slot_id": selected_slot, "expires_at": expiry.isoformat(), "ttl_seconds": ttl_seconds},
    )

    return {
        "acquired": True,
        "slot_id": selected_slot,
        "queue_reason": None,
        "expires_at": expiry,
        "ttl_seconds": ttl_seconds,
    }


def release_slot_lease(db: Session, slot_id: str, run_id: str | None = None) -> dict[str, Any]:
    lease = db.query(SlotLease).filter(SlotLease.slot_id == slot_id).with_for_update().first()
    if lease is None:
        return {"released": False, "slot_id": slot_id, "run_id": run_id, "reason": "slot_not_found"}

    if run_id is not None and lease.run_id != run_id:
        return {
            "released": False,
            "slot_id": slot_id,
            "run_id": run_id,
            "reason": "slot_owned_by_different_run",
        }

    now = _utcnow()
    owning_run_id = lease.run_id

    lease.lease_state = "released"
    lease.expires_at = now
    lease.heartbeat_at = now

    run = db.query(Run).filter(Run.id == owning_run_id).first()
    if run is not None and run.slot_id == slot_id:
        run.slot_id = None

    _add_run_event(
        db,
        run_id=owning_run_id,
        event_type="slot_released",
        payload={"slot_id": slot_id},
    )

    return {"released": True, "slot_id": slot_id, "run_id": owning_run_id, "reason": None}


def heartbeat_slot_lease(db: Session, slot_id: str, run_id: str) -> dict[str, Any]:
    lease = (
        db.query(SlotLease)
        .filter(SlotLease.slot_id == slot_id, SlotLease.run_id == run_id)
        .with_for_update()
        .first()
    )
    if lease is None:
        return {
            "heartbeat_updated": False,
            "slot_id": slot_id,
            "run_id": run_id,
            "reason": "lease_not_found",
            "expires_at": None,
        }

    now = _utcnow()
    lease_expires = _normalize_utc(lease.expires_at)

    if lease.lease_state != "leased" or lease_expires <= now:
        _expire_lease_and_link_run(db, lease=lease, now=now, source="slot_heartbeat")
        _add_run_event(
            db,
            run_id=run_id,
            event_type="slot_heartbeat_rejected",
            payload={"slot_id": slot_id, "reason": "lease_expired"},
        )

        return {
            "heartbeat_updated": False,
            "slot_id": slot_id,
            "run_id": run_id,
            "reason": "lease_expired",
            "expires_at": None,
        }

    ttl_seconds = _lease_ttl_seconds()
    new_expiry = now + timedelta(seconds=ttl_seconds)

    lease.heartbeat_at = now
    lease.expires_at = new_expiry

    _add_run_event(
        db,
        run_id=run_id,
        event_type="slot_heartbeat",
        payload={"slot_id": slot_id, "expires_at": new_expiry.isoformat(), "ttl_seconds": ttl_seconds},
    )

    return {
        "heartbeat_updated": True,
        "slot_id": slot_id,
        "run_id": run_id,
        "reason": None,
        "expires_at": new_expiry,
    }


def reap_expired_slot_leases(db: Session) -> dict[str, Any]:
    now = _utcnow()

    leases = db.query(SlotLease).filter(SlotLease.lease_state == "leased").with_for_update().all()

    expired_count = 0
    expired_slots: list[str] = []

    for lease in leases:
        if _normalize_utc(lease.expires_at) > now:
            continue

        _expire_lease_and_link_run(db, lease=lease, now=now, source="slot_reaper")

        expired_count += 1
        expired_slots.append(lease.slot_id)

    return {"expired_count": expired_count, "expired_slots": sorted(expired_slots)}


def list_slot_states(db: Session) -> list[dict[str, Any]]:
    now = _utcnow()
    slot_ids = _configured_slot_ids()
    lease_map = _load_slot_lease_map(db, slot_ids)

    states: list[dict[str, Any]] = []
    for slot_id in slot_ids:
        lease = lease_map.get(slot_id)
        if lease is None:
            states.append(
                {
                    "slot_id": slot_id,
                    "state": "available",
                    "run_id": None,
                    "lease_state": None,
                    "expires_at": None,
                    "heartbeat_at": None,
                }
            )
            continue

        effective_state = lease.lease_state
        if lease.lease_state == "leased" and _normalize_utc(lease.expires_at) <= now:
            effective_state = "expired"
        elif lease.lease_state == "leased":
            effective_state = "leased"

        states.append(
            {
                "slot_id": slot_id,
                "state": effective_state,
                "run_id": lease.run_id,
                "lease_state": lease.lease_state,
                "expires_at": lease.expires_at,
                "heartbeat_at": lease.heartbeat_at,
            }
        )

    return states
