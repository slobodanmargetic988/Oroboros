# Observability and Trace Correlation (MYO-35)

Host-only observability contract for API, worker, and deploy scripts.

## Structured logging fields
All structured logs emit the following correlation keys when available:
- `trace_id`
- `run_id`
- `slot_id`
- `commit_sha`

Implementations:
- API logs via `backend/app/services/observability.py`
- Worker logs via `worker/worker/observability.py`
- Deploy/rollback script logs via JSON lines in `scripts/deploy.sh` and `scripts/rollback.sh`

## Core metrics export
Core runtime metrics are available at:
- `GET /api/metrics/core`

Payload includes:
- `queue_depth`
- `duration_seconds.avg`
- `duration_seconds.max`
- `duration_seconds.sample_size`
- `failure_rate`
- `failed_runs`
- `terminal_runs`

## Trace propagation path
1. API middleware accepts `X-Trace-Id` or generates one.
2. API writes trace to run context metadata (`trace_id`) during run creation.
3. Worker claim path reads trace from run context and carries it through worker events/logs.
4. Worker injects trace env into all execution/check commands:
   - `TRACE_ID` / `OUROBOROS_TRACE_ID`
   - `RUN_ID` / `OUROBOROS_RUN_ID`
   - `SLOT_ID` / `OUROBOROS_SLOT_ID`
   - `COMMIT_SHA` / `OUROBOROS_COMMIT_SHA` (when known)
5. Deploy/rollback scripts emit structured logs using inherited env values.

No Docker/Compose/Kubernetes/container runtime assumptions are used.
