# Base Linux Runtime Topology (MYO-15)

This document defines the host-native process topology for:
- `web-main` (production web surface)
- `web-preview-1`
- `web-preview-2`
- `web-preview-3`
- `api`
- `worker`
- `postgres`
- `redis`
- `reverse-proxy`

## Process Manager
- Baseline process manager: **systemd**
- Unit files: `infra/systemd/*.service`
- Env files: `infra/systemd/env/*.env` (installed to `/etc/oroboros/`)
- Runtime code path: `/srv/oroboros/current` (atomic release symlink target)

## Service Users
- `ouroboros-worker.service` runs as dedicated host identity `oroboros-worker`.
- `ouroboros-api.service` and web surfaces run as `oroboros`.
- Reverse proxy runs as `caddy`.

Worker security guardrails and policy controls are documented in:
- `docs/worker-security-guardrails.md`

## Service Topology

| Service | systemd Unit | Bind Address | Port | Hostname / Route |
|---|---|---|---:|---|
| reverse-proxy (Caddy) | `ouroboros-caddy.service` | `127.0.0.1` | 8088 | Host-based routes via Caddy |
| web-main | `ouroboros-web@main.service` | `127.0.0.1` | 3100 | `app.example.com` |
| web-preview-1 | `ouroboros-web@preview1.service` | `127.0.0.1` | 3101 | `preview1.example.com` |
| web-preview-2 | `ouroboros-web@preview2.service` | `127.0.0.1` | 3102 | `preview2.example.com` |
| web-preview-3 | `ouroboros-web@preview3.service` | `127.0.0.1` | 3103 | `preview3.example.com` |
| api-preview-1 | host-native slot runtime helper | `127.0.0.1` | 8101 | slot `preview-1` backend |
| api-preview-2 | host-native slot runtime helper | `127.0.0.1` | 8102 | slot `preview-2` backend |
| api-preview-3 | host-native slot runtime helper | `127.0.0.1` | 8103 | slot `preview-3` backend |
| api | `ouroboros-api.service` | `127.0.0.1` | 8000 | `api.example.com` (via proxy) |
| worker | `ouroboros-worker.service` | `127.0.0.1` | 8090 | `worker.example.com` (via proxy) |
| postgres | distro package service (`postgresql.service`) | `127.0.0.1` | 5432 | internal DB endpoint |
| redis | distro package service (`redis.service`) | `127.0.0.1` | 6379 | internal queue endpoint |

## Reverse Proxy Routes
Defined in `infra/caddy/Caddyfile`:
- `app.example.com` -> `127.0.0.1:3100`
- `preview1.example.com` -> `127.0.0.1:3101`
- `preview2.example.com` -> `127.0.0.1:3102`
- `preview3.example.com` -> `127.0.0.1:3103`
- `api.example.com` -> `127.0.0.1:8000`
- `worker.example.com` -> `127.0.0.1:8090`

Preview slot-specific provisioning/health contract:
- `docs/preview-runtime-slots.md`
- `docs/fullstack-preview-ops-runbook.md`
- `scripts/preview-slots-provision.sh`
- `scripts/preview-slots-health-check.sh`

## Core Environment Values
- API (`/etc/oroboros/api.env`):
  - `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/builder_control`
- Worker (`/etc/oroboros/worker.env`):
  - `REDIS_URL=redis://127.0.0.1:6379/0`
  - `WORKER_POLL_INTERVAL_SECONDS=5`
  - `WORKER_HEALTH_PORT=8090`
  - `WORKER_ARTIFACT_ROOT=/srv/oroboros/artifacts/runs`
- Web surfaces (`/etc/oroboros/web-*.env`):
  - `WEB_ROOT=/srv/oroboros/current/infra/<web-root>`
  - `WEB_PORT=<3100..3103>`
  - Preview slots include `WEB_API_PROXY_TARGET=http://127.0.0.1:810{slot}`

## Health Endpoints
- `web-main`: `/health` on port `3100`
- `web-preview-1`: `/health` on port `3101`
- `web-preview-2`: `/health` on port `3102`
- `web-preview-3`: `/health` on port `3103`
- `api`: `http://127.0.0.1:8000/health`
- `api-preview-1`: `http://127.0.0.1:8101/health`
- `api-preview-2`: `http://127.0.0.1:8102/health`
- `api-preview-3`: `http://127.0.0.1:8103/health`
- `worker`: `http://127.0.0.1:8090/health`
- `postgres`: `pg_isready -h 127.0.0.1 -U postgres -d builder_control`
- `redis`: `redis-cli -h 127.0.0.1 ping`

Use `scripts/runtime-health-check.sh` for one-command verification.

Per-slot backend lifecycle helper:
- `scripts/preview-backend-runtime.sh`

## Scripted Deploy (MYO-26)
- Command: `./scripts/deploy.sh <commit_sha>`
- Release path: `/srv/oroboros/releases/<commit_sha>`
- Atomic switch: `/srv/oroboros/current`
- Health gate: `scripts/runtime-health-check.sh` (rollback on failure)
- Full flow: `docs/deployment-flow.md`

## Scripted Rollback (MYO-28)
- Command: `./scripts/rollback.sh <release_id>`
- Target: existing host release at `/srv/oroboros/releases/<release_id>`
- Atomic switch: `/srv/oroboros/current`
- Health gate: `scripts/runtime-health-check.sh` (restore previous target on failure)
- Release registry updates recorded in control-plane DB (`releases` table)

## Scheduled Maintenance Jobs (MYO-41)
Scheduled as host-native `systemd` timers (no container scheduler dependency):

| Job | Timer | Service | Frequency | Command |
|---|---|---|---|---|
| Stale lease cleanup | `ouroboros-maintenance-stale-leases.timer` | `ouroboros-maintenance-stale-leases.service` | every 15 minutes | `scripts/maintenance-stale-lease-cleanup.sh` |
| Preview DB reset integrity audit | `ouroboros-maintenance-preview-reset-audit.timer` | `ouroboros-maintenance-preview-reset-audit.service` | hourly | `scripts/maintenance-preview-reset-integrity.sh --lookback-hours 24 --running-grace-minutes 90` |
| Daily deployment + service health summary | `ouroboros-maintenance-daily-health-summary.timer` | `ouroboros-maintenance-daily-health-summary.service` | daily at 03:30 (with randomized delay) | `scripts/maintenance-daily-health-summary.sh --output-dir /srv/oroboros/artifacts/maintenance` |

Daily health summaries are written to:
- `/srv/oroboros/artifacts/maintenance/daily-health-summary-YYYYMMDD.json`

## Preview Smoke/E2E Harness (MYO-32)
- Command: `./scripts/preview-smoke-e2e.sh --preview-url <preview_url>`
- Changed routes: add repeated `--changed-route /path`
- Host-routed local execution: add `--proxy-origin http://127.0.0.1:8088`
- Output: machine-readable JSON artifact and stdout summary for validation pipeline use
- Optional persistence: `--run-id <run_id> --persist-validation` stores records in `validation_checks` + `run_artifacts`

## Non-container Constraint
This topology intentionally avoids Docker/Compose/Kubernetes and runs services directly as host processes under `systemd`.
