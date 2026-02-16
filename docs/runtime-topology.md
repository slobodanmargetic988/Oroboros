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

## Service Topology

| Service | systemd Unit | Bind Address | Port | Hostname / Route |
|---|---|---|---:|---|
| reverse-proxy (Caddy) | `ouroboros-caddy.service` | `127.0.0.1` | 8088 | Host-based routes via Caddy |
| web-main | `ouroboros-web@main.service` | `127.0.0.1` | 3100 | `app.example.com` |
| web-preview-1 | `ouroboros-web@preview1.service` | `127.0.0.1` | 3101 | `preview1.example.com` |
| web-preview-2 | `ouroboros-web@preview2.service` | `127.0.0.1` | 3102 | `preview2.example.com` |
| web-preview-3 | `ouroboros-web@preview3.service` | `127.0.0.1` | 3103 | `preview3.example.com` |
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
- `scripts/preview-slots-provision.sh`
- `scripts/preview-slots-health-check.sh`

## Core Environment Values
- API (`/etc/oroboros/api.env`):
  - `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/builder_control`
- Worker (`/etc/oroboros/worker.env`):
  - `REDIS_URL=redis://127.0.0.1:6379/0`
  - `WORKER_POLL_INTERVAL_SECONDS=5`
  - `WORKER_HEALTH_PORT=8090`
- Web surfaces (`/etc/oroboros/web-*.env`):
  - `WEB_ROOT=/srv/oroboros/current/infra/<web-root>`
  - `WEB_PORT=<3100..3103>`

## Health Endpoints
- `web-main`: `/health` on port `3100`
- `web-preview-1`: `/health` on port `3101`
- `web-preview-2`: `/health` on port `3102`
- `web-preview-3`: `/health` on port `3103`
- `api`: `http://127.0.0.1:8000/health`
- `worker`: `http://127.0.0.1:8090/health`
- `postgres`: `pg_isready -h 127.0.0.1 -U postgres -d builder_control`
- `redis`: `redis-cli -h 127.0.0.1 ping`

Use `scripts/runtime-health-check.sh` for one-command verification.

## Scripted Deploy (MYO-26)
- Command: `./scripts/deploy.sh <commit_sha>`
- Release path: `/srv/oroboros/releases/<commit_sha>`
- Atomic switch: `/srv/oroboros/current`
- Health gate: `scripts/runtime-health-check.sh` (rollback on failure)
- Full flow: `docs/deployment-flow.md`

## Non-container Constraint
This topology intentionally avoids Docker/Compose/Kubernetes and runs services directly as host processes under `systemd`.
