# Preview Runtime Slots (MYO-20 / MYO-23)

This document defines fixed preview slot provisioning for host-level deployment.

Canonical fullstack slot contract is defined in:
- `docs/fullstack-preview-slot-runtime-contract.md`

## Dedicated Preview URLs
- `preview1.example.com`
- `preview2.example.com`
- `preview3.example.com`

## Slot-to-Port Mapping

| Slot ID | URL | systemd unit | Local port | Static root |
|---|---|---|---:|---|
| preview-1 (`preview1`) | `preview1.example.com` | `ouroboros-web@preview1` | 3101 | `/srv/oroboros/current/infra/web-preview-1` |
| preview-2 (`preview2`) | `preview2.example.com` | `ouroboros-web@preview2` | 3102 | `/srv/oroboros/current/infra/web-preview-2` |
| preview-3 (`preview3`) | `preview3.example.com` | `ouroboros-web@preview3` | 3103 | `/srv/oroboros/current/infra/web-preview-3` |

Routing is handled by Caddy in `infra/caddy/Caddyfile`:
- `preview1.example.com -> 127.0.0.1:3101`
- `preview2.example.com -> 127.0.0.1:3102`
- `preview3.example.com -> 127.0.0.1:3103`

API routing contract:
- Preview frontend uses relative `/api` in preview builds.
- Slot-local web surface proxies `/api` to matching slot backend:
  - `3101 -> 8101`
  - `3102 -> 8102`
  - `3103 -> 8103`
- Mapping is configured via `WEB_API_PROXY_TARGET` in:
  - `infra/systemd/env/web-preview1.env`
  - `infra/systemd/env/web-preview2.env`
  - `infra/systemd/env/web-preview3.env`
- Publish diagnostics include `vite_api_base_url` and `slot_backend_url` in `preview.publish.log`.

## Per-slot Backend Runtime Helpers (MYO-57)

Preview backend slot ports are fixed:
- `preview-1` -> `127.0.0.1:8101`
- `preview-2` -> `127.0.0.1:8102`
- `preview-3` -> `127.0.0.1:8103`

Helper script:
```bash
./scripts/preview-backend-runtime.sh status --slot preview-1
./scripts/preview-backend-runtime.sh start --slot preview-1
./scripts/preview-backend-runtime.sh restart --slot preview-1
./scripts/preview-backend-runtime.sh health --slot preview-1
./scripts/preview-backend-runtime.sh stop --slot preview-1
```

Runtime helper responses are JSON and machine-parseable for worker and manual operations.
Startup enforces slot->DB binding (`preview-1 -> app_preview_1`, etc.) and fails fast on mismatch.

Worker publish sequence for fullstack readiness:
1. Frontend build + sync to slot web root.
2. Backend dependency sync from run branch.
3. Slot-safe migrations on slot preview DB.
4. Slot backend restart.
5. Readiness gate (`FE /health` + `BE /health`) before `preview_ready`.
6. Slot backend integration smoke check (`POST /api/slots/{slot}/heartbeat` + `GET /api/slots` readback) with slot-tagged artifact.

## Dev Fallback (Direct Port Mode)

When reverse proxy routing is unavailable, run each preview surface directly with its slot API upstream:
```bash
python3 scripts/run-web-surface.py --root infra/web-preview-1 --port 3101 --api-target http://127.0.0.1:8101
python3 scripts/run-web-surface.py --root infra/web-preview-2 --port 3102 --api-target http://127.0.0.1:8102
python3 scripts/run-web-surface.py --root infra/web-preview-3 --port 3103 --api-target http://127.0.0.1:8103
```

If direct frontend-to-backend calls are required instead of `/api` proxying, ensure backend CORS allowlist includes preview origins (`3101/3102/3103` and preview domains).

## Provisioning Automation

Install/update slot env files and start the three preview services:
```bash
./scripts/preview-slots-provision.sh
```

Dry-run mode:
```bash
./scripts/preview-slots-provision.sh --dry-run
```

## Health Checks (per slot)

Direct + routed checks:
```bash
./scripts/preview-slots-health-check.sh
```

This is host-only provisioning: no Docker/Compose/Kubernetes/containers.

## Deterministic DB Reset + Seed Strategy (MYO-23)

Each preview slot has a dedicated database:
- `preview-1` (`preview1`) -> `app_preview_1`
- `preview-2` (`preview2`) -> `app_preview_2`
- `preview-3` (`preview3`) -> `app_preview_3`

Reset script per slot DB:
```bash
./scripts/preview-db-reset.sh --slot preview1
```

Deterministic seed apply:
```bash
./scripts/preview-db-seed.sh --slot preview1 --seed-version v1
```

Combined reset + load strategy (seed or snapshot):
```bash
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id <run_id> --strategy seed --seed-version v1
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id <run_id> --strategy snapshot --snapshot-version <snapshot_version>
```

Apply slot-safe migrations for preview DB:
```bash
./scripts/preview-slot-migrate.sh --slot preview-1
```

Validate migration target without executing:
```bash
./scripts/preview-slot-migrate.sh --slot preview-1 --dry-run
```

Dry-run examples:
```bash
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id dry-run --strategy seed --seed-version v1 --dry-run
```

## Slot Allocation Flow Integration

Use allocation CLI to lock a slot and execute the deterministic DB reset/seed flow as part of allocation:
```bash
./scripts/preview-slot-allocate.sh --run-id <run_id> --seed-version v1 --strategy seed
```

This flow records per-run reset provenance in control-plane table `preview_db_resets`:
- `run_id`
- `slot_id`
- `db_name`
- `strategy`
- `seed_version`
- `snapshot_version`
- `reset_status`
- timestamps and details payload
