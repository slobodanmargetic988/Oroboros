# Slot Lease Manager Contract (MYO-21)

Defines A1 backend slot leasing behavior for fixed preview slots.

## Fixed Slot Pool
- `preview-1`
- `preview-2`
- `preview-3`

Configurable via backend settings:
- `slot_ids_csv` (default: `preview-1,preview-2,preview-3`)
- `slot_lease_ttl_seconds` (default: `1800`)

## Queue Behavior When All Slots Are Occupied
- Acquire response returns:
  - `acquired: false`
  - `queue_reason: WAITING_FOR_SLOT`
- Run remains queued while waiting for available lease.
- Event recorded: `slot_waiting` with occupied slot list.

## API Endpoints
- `GET /api/slots`
  - Returns slot state for each configured slot.
- `POST /api/slots/acquire`
  - Body: `{ "run_id": "<id>" }`
  - Atomically acquires first available slot or returns queue behavior.
- `POST /api/slots/{slot_id}/heartbeat`
  - Body: `{ "run_id": "<id>" }`
  - Extends lease expiry by TTL for active lease.
- `POST /api/slots/{slot_id}/release`
  - Body: `{ "run_id": "<id>" }` (optional run guard)
  - Releases slot and clears `run.slot_id`.
- `POST /api/slots/reap-expired`
  - Marks stale leases expired and clears slot assignment on runs.
- `GET /api/slots/contract`
  - Returns queue behavior contract and fixed slot IDs.

## Event Emissions
- `slot_acquired`
- `slot_acquire_idempotent`
- `slot_released`
- `slot_heartbeat`
- `slot_heartbeat_rejected`
- `slot_expired`
- `slot_waiting`
