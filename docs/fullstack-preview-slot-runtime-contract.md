# Fullstack Preview Slot Runtime Contract (MYO-56)

This document is the single source of truth for fullstack preview slot runtime behavior.

## Scope

- Host-native runtime only.
- No Docker, Compose, Kubernetes, or container sidecars.
- Each slot must isolate frontend, backend runtime, and preview database.

## Canonical Slot Mapping

| Slot ID | Frontend Port | Backend API Port | Preview DB |
|---|---:|---:|---|
| `preview-1` | `3101` | `8101` | `app_preview_1` |
| `preview-2` | `3102` | `8102` | `app_preview_2` |
| `preview-3` | `3103` | `8103` | `app_preview_3` |

Host aliases (`preview1`, `preview2`, `preview3`) are allowed only as compatibility shortcuts for DNS/service names. Slot identity is canonicalized to `preview-<n>`.

## Routing Contract

- Preview frontend must call relative `/api` by default.
- Reverse proxy or web-surface proxy must map slot-local `/api` to that same slot backend:
  - `preview-1` frontend -> backend `127.0.0.1:8101`
  - `preview-2` frontend -> backend `127.0.0.1:8102`
  - `preview-3` frontend -> backend `127.0.0.1:8103`
- Cross-slot backend routing is forbidden.
- Dev fallback mode may call `http://127.0.0.1:810{slot}` directly when reverse proxy is not active.

## Environment Contract

### Shared runtime variables

- `SLOT_IDS_CSV=preview-1,preview-2,preview-3`
- `WORKER_PREVIEW_WEB_ROOT_TEMPLATE=/srv/oroboros/current/infra/web-preview-{slot}`
- `WORKER_PREVIEW_RUNTIME_SCRIPTS_DIR=/srv/oroboros/current/scripts`

### Per-slot backend runtime variables

- `SLOT_ID`: canonical slot id (`preview-1`, `preview-2`, `preview-3`)
- `SLOT_NUM`: numeric suffix (`1`, `2`, `3`)
- `SLOT_BACKEND_PORT`: API port (`8101`, `8102`, `8103`)
- `SLOT_DB_NAME`: preview DB name (`app_preview_1`, `app_preview_2`, `app_preview_3`)
- `SLOT_WORKTREE_PATH`: assigned worktree path for slot runtime execution
- `DATABASE_URL`: must point to slot preview DB when running slot backend

### Production-specific variables

- `DEPLOY_BACKEND_RELOAD_CMD`: host-native reload command used after approved merge.
- `DEPLOY_BACKEND_HEALTHCHECK_CMD`: post-reload backend health gate command.

### Dev/local variables

- `WORKER_SLOT_API_DIRECT_TEMPLATE=http://127.0.0.1:810{slot}`
- `WORKER_SLOT_PREVIEW_HOST_TEMPLATE=preview{slot}.example.com`

## Process Ownership and Lifecycle

- Process manager: `systemd` in production-like host runtime.
- Preview frontend surfaces are long-running services (`ouroboros-web@preview1/2/3`).
- Preview backend slot runtimes are independently managed processes with explicit commands:
  - start per slot
  - restart per slot
  - stop per slot
  - status/health per slot
- Worker publish flow must invoke slot-scoped backend lifecycle commands and never restart unrelated slots.
- Slot release/expiry must stop or detach slot backend runtime safely.

## Database and Migration Safety Contract

- Slot backend runtime for `preview-<n>` must always resolve to `app_preview_<n>`.
- Preview runtime startup must fail fast if slot->DB mapping is invalid.
- Preview migration target must resolve deterministically from slot id.
- Any preview-mode migration targeting non-preview DB (for example production DB) must hard-fail with explicit diagnostics.

## Security Boundaries

- Subprocess command execution must remain allowlisted.
- Worker subprocess environment must remain allowlisted + blocklisted as defined in runtime config.
- File operations must stay within configured repository/worktree/artifact roots.
- Slot runtime scripts must reject unknown slot ids and unsafe path traversal.
- Preview runtime must not inherit production-only secrets by default.

## Diagnostics Contract

- Every publish/restart/migration/dependency-sync step must emit machine-parseable output.
- Artifacts must capture:
  - frontend publish output
  - dependency sync output
  - migration output
  - backend restart output
  - FE/BE readiness checks

## Non-container Policy

This goal is explicitly host-native:
- Allowed: `systemd`, host processes, host filesystem paths, host-local ports.
- Not allowed: Docker, Compose, Kubernetes, or any container orchestration runtime.
