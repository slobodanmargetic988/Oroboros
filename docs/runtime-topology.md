# Base Linux Runtime Topology (MYO-15)

This document defines the initial process topology for:
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
- Baseline process manager: **Docker Compose**
- Compose file: `infra/docker-compose.runtime.yml`

## Service Topology

| Service | Container Name | Internal Port | Host Port | Hostname / Route |
|---|---|---:|---:|---|
| reverse-proxy | ouroboros-reverse-proxy | 80 | 8088 | Host-based routes via Caddy |
| web-main | ouroboros-web-main | 8080 | n/a | `app.example.com` |
| web-preview-1 | ouroboros-web-preview-1 | 8080 | n/a | `preview1.example.com` |
| web-preview-2 | ouroboros-web-preview-2 | 8080 | n/a | `preview2.example.com` |
| web-preview-3 | ouroboros-web-preview-3 | 8080 | n/a | `preview3.example.com` |
| api | ouroboros-api | 8000 | 8000 | `api.example.com` (via proxy) |
| worker | ouroboros-worker | 8090 | 8090 | `worker.example.com` (via proxy) |
| postgres | ouroboros-postgres | 5432 | 5432 | internal DB endpoint |
| redis | ouroboros-redis | 6379 | 6379 | internal queue endpoint |

## Reverse Proxy Routes
Defined in `infra/caddy/Caddyfile`:
- `app.example.com` -> `web-main:8080`
- `preview1.example.com` -> `web-preview-1:8080`
- `preview2.example.com` -> `web-preview-2:8080`
- `preview3.example.com` -> `web-preview-3:8080`
- `api.example.com` -> `api:8000`
- `worker.example.com` -> `worker:8090`

## Core Environment Values
- API:
  - `DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/builder_control`
- Worker:
  - `REDIS_URL=redis://redis:6379/0`
  - `WORKER_POLL_INTERVAL_SECONDS=5`
  - `WORKER_HEALTH_PORT=8090`
- Postgres:
  - `POSTGRES_DB=builder_control`
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=postgres`

## Health Endpoints
- `web-main`: `/health`
- `web-preview-1`: `/health`
- `web-preview-2`: `/health`
- `web-preview-3`: `/health`
- `api`: `http://127.0.0.1:8000/health`
- `worker`: `http://127.0.0.1:8090/health`
- `postgres`: `pg_isready -U postgres -d builder_control`
- `redis`: `redis-cli ping`

Use `scripts/runtime-health-check.sh` for one-command verification.
