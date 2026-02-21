# Fullstack Preview Ops Runbook (MYO-64)

This runbook is the operational guide for host-native fullstack preview lifecycle (frontend + backend + preview DB per slot).

## Startup Matrix

| Surface | Unit / Command | Port | Env file | Health check |
|---|---|---:|---|---|
| API (control) | `ouroboros-api.service` | `8000` | `/etc/oroboros/api.env` | `curl -fsS http://127.0.0.1:8000/health` |
| Worker | `ouroboros-worker.service` | `8090` | `/etc/oroboros/worker.env` | `curl -fsS http://127.0.0.1:8090/health` |
| Web main | `ouroboros-web@main.service` | `3100` | `/etc/oroboros/web-main.env` | `curl -fsS http://127.0.0.1:3100/health` |
| Web preview-1 | `ouroboros-web@preview1.service` | `3101` | `/etc/oroboros/web-preview1.env` | `curl -fsS http://127.0.0.1:3101/health` |
| Web preview-2 | `ouroboros-web@preview2.service` | `3102` | `/etc/oroboros/web-preview2.env` | `curl -fsS http://127.0.0.1:3102/health` |
| Web preview-3 | `ouroboros-web@preview3.service` | `3103` | `/etc/oroboros/web-preview3.env` | `curl -fsS http://127.0.0.1:3103/health` |
| Slot backend preview-1 | `scripts/preview-backend-runtime.sh start --slot preview-1` | `8101` | slot runtime env/template | `curl -fsS http://127.0.0.1:8101/health` |
| Slot backend preview-2 | `scripts/preview-backend-runtime.sh start --slot preview-2` | `8102` | slot runtime env/template | `curl -fsS http://127.0.0.1:8102/health` |
| Slot backend preview-3 | `scripts/preview-backend-runtime.sh start --slot preview-3` | `8103` | slot runtime env/template | `curl -fsS http://127.0.0.1:8103/health` |
| Caddy | `ouroboros-caddy.service` | `8088` | `infra/caddy/Caddyfile` | `curl -fsS -H 'Host: app.example.com' http://127.0.0.1:8088/health` |

## Bring-up (Command-ready)

```bash
./scripts/systemd-install-runtime.sh
./scripts/runtime-up.sh
./scripts/preview-backend-runtime.sh restart --slot preview-1
./scripts/preview-backend-runtime.sh restart --slot preview-2
./scripts/preview-backend-runtime.sh restart --slot preview-3
./scripts/runtime-health-check.sh
```

Validate slot-local API wiring:

```bash
curl -fsS http://127.0.0.1:3101/api/health
curl -fsS http://127.0.0.1:3102/api/health
curl -fsS http://127.0.0.1:3103/api/health
```

## Slot Troubleshooting

### Stuck slot / run waiting forever
1. Inspect slot occupancy:
   - `curl -fsS http://127.0.0.1:8000/api/slots | python3 -m json.tool`
2. Reap expired leases:
   - `curl -fsS -X POST http://127.0.0.1:8000/api/slots/reap-expired`
3. If slot is still stale, release explicitly:
   - `curl -fsS -X POST http://127.0.0.1:8000/api/slots/<slot_id>/release -H 'Content-Type: application/json' -d '{"run_id":"<run_id>"}'`

### Backend restart failed for a slot
1. Restart and capture machine-parseable output:
   - `./scripts/preview-backend-runtime.sh restart --slot preview-1`
2. Inspect runtime log:
   - `tail -n 200 /tmp/oroboros-preview-backend/preview-1.log`
3. Confirm worktree + DB binding:
   - `./scripts/preview-backend-runtime.sh status --slot preview-1`

### Wrong backend target / cross-slot API suspicion
1. Verify per-slot proxy target:
   - `cat infra/systemd/env/web-preview1.env`
2. Verify endpoint from Run Details (Frontend preview and Backend preview links).
3. Probe slot-local API via web surface:
   - `curl -fsS http://127.0.0.1:3101/api/health`
4. Compare with direct backend health:
   - `curl -fsS http://127.0.0.1:8101/health`

### Slot migration or DB target failure
1. Validate migration target contract (no execution):
   - `./scripts/preview-slot-migrate.sh --slot preview-1 --dry-run`
2. Run migration explicitly:
   - `./scripts/preview-slot-migrate.sh --slot preview-1`
3. If command reports unsafe DB target, fix `PREVIEW_BACKEND_DATABASE_URL_TEMPLATE` and re-run.

## Approval/Merge/Deploy Behavior (Backend-changing runs)

On approval:
1. Merge-gate checks run.
2. Commit merges to `main`.
3. Safe git-push hook runs (`manual` / `auto` / `dry-run` mode).
4. Deploy hook runs backend reload command.
5. Deploy health gate runs backend health check.
6. Run transitions to `merged` only after push/deploy hooks pass.

Failure behavior:
- Push hook failure transitions run to `failed` with `DEPLOY_PUSH_FAILED`.
- Push diagnostics artifact is attached (`deploy_git_push_log`).
- Deploy hook failure transitions run to `failed` with `DEPLOY_HEALTHCHECK_FAILED`.
- Deploy diagnostics artifact is attached (`deploy_backend_reload_log`).
- Rollback guidance is included in run events.

## Security Notes (Host-native model)

- No container runtime is used; all services run as host processes.
- Keep secrets in `/etc/oroboros/*.env` with least-privilege permissions.
- Worker subprocess allowlist/blocklist must remain enforced.
- Slot migration helper blocks non-preview DB targets.
- Slot runtime scripts reject invalid slot IDs and unsafe DB bindings.

## Rollback Notes

Release rollback:
```bash
./scripts/release-registry.sh list
./scripts/rollback.sh <release_id>
./scripts/runtime-health-check.sh
```

Slot runtime rollback (single slot):
```bash
./scripts/preview-backend-runtime.sh stop --slot preview-1
./scripts/preview-backend-runtime.sh start --slot preview-1
```

## Production Domain and CORS Guidance

- Production domains are host-routed via Caddy (`app.example.com`, `preview1.example.com`, `preview2.example.com`, `preview3.example.com`, `api.example.com`).
- Backend CORS allowlist must include:
  - preview origins (`https://preview1.example.com`, `https://preview2.example.com`, `https://preview3.example.com`)
  - app origin(s) as needed
- For direct-port operational checks, allowlist local preview ports (`3101/3102/3103`) to avoid preflight failures during diagnostics.
