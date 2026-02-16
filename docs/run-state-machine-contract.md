# Run State Machine Contract (MYO-17)

This contract is the canonical run lifecycle and API skeleton used by Agent-1 (backend), Agent-2 (frontend), and Agent-3 (infra).

## Canonical States
1. `queued`
2. `planning`
3. `editing`
4. `testing`
5. `preview_ready`
6. `needs_approval`
7. `approved`
8. `merging`
9. `deploying`
10. `merged`
11. `failed`
12. `canceled`
13. `expired`

Terminal states: `merged`, `failed`, `canceled`, `expired`.

## Allowed Transitions
- `queued` -> `planning`, `canceled`, `failed`, `expired`
- `planning` -> `editing`, `canceled`, `failed`, `expired`
- `editing` -> `testing`, `canceled`, `failed`, `expired`
- `testing` -> `preview_ready`, `failed`, `canceled`, `expired`
- `preview_ready` -> `needs_approval`, `failed`, `canceled`, `expired`
- `needs_approval` -> `approved`, `failed`, `canceled`, `expired`
- `approved` -> `merging`, `failed`, `canceled`, `expired`
- `merging` -> `deploying`, `failed`, `canceled`
- `deploying` -> `merged`, `failed`, `canceled`
- terminal states -> no further transitions

Server-side enforcement is implemented in:
- `backend/app/domain/run_state_machine.py`
- `POST /api/runs/{run_id}/transition`
- `POST /api/runs/{run_id}/approve`
- `POST /api/runs/{run_id}/reject`

## Standard Failure Reason Codes
- `WAITING_FOR_SLOT`
- `VALIDATION_FAILED`
- `CHECKS_FAILED`
- `MERGE_CONFLICT`
- `MIGRATION_FAILED`
- `DEPLOY_HEALTHCHECK_FAILED`
- `AGENT_TIMEOUT`
- `AGENT_CANCELED`
- `PREVIEW_EXPIRED`
- `POLICY_REJECTED`
- `UNKNOWN_ERROR`

Rule:
- `failure_reason_code` is required for transitions to `failed`.
- `failure_reason_code` must not be provided for non-`failed` transitions.

## API Skeleton (MYO-17)

### Runs
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/transition`
- `POST /api/runs/{run_id}/cancel`
- `POST /api/runs/{run_id}/retry`
- `GET /api/runs/contract`

### Events
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/events/stream` (stub placeholder)

### Checks
- `GET /api/runs/{run_id}/checks`

### Approvals
- `GET /api/runs/{run_id}/approvals`
- `POST /api/runs/{run_id}/approve`
- `POST /api/runs/{run_id}/reject`

## Parallel Track Expectations
- Agent-1 consumes this contract for backend state transitions and event semantics.
- Agent-2 consumes this contract for UI state badges/actions and allowed user actions per state.
- Agent-3 consumes this contract for worker/proxy/deploy orchestration hooks and failure code reporting.
