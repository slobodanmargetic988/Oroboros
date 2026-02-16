# Scripted Deployment Flow (MYO-26)

This deployment flow is host-only and container-free.

## Goal
- Build a release from a commit SHA into `/srv/oroboros/releases/<commit_sha>`.
- Atomically switch `/srv/oroboros/current` to that release.
- Restart host services and gate success on health checks.

## Command
```bash
./scripts/deploy.sh <commit_sha>
```

Rollback command:
```bash
./scripts/rollback.sh <release_id>
```

## What `deploy.sh` does
1. Validates the commit exists in the source repo.
2. Creates a release directory for the commit if it does not already exist.
3. Builds release assets in the release directory:
   - Frontend build (`npm ci && npm run build`) when `npm` is available.
   - Copies built frontend output into `infra/web-main`.
   - Creates backend + worker virtual environments and installs project packages.
4. Atomically switches `/srv/oroboros/current` to the release using symlink swap.
5. Restarts systemd services for api/worker/web/caddy.
6. Runs post-deploy health gate (`scripts/runtime-health-check.sh` from `current`).
7. If health gate fails, restores previous `current` symlink and restarts services.
8. Persists release metadata updates in control-plane `releases` table.

## What `rollback.sh` does
1. Validates target release directory exists at `/srv/oroboros/releases/<release_id>`.
2. Persists rollback-in-progress state to release registry.
3. Atomically switches `/srv/oroboros/current` to target release.
4. Restarts host services (unless skipped).
5. Runs health gate from active `current` release.
6. If health check fails, restores previous symlink target, restarts services, records rollback failure, and exits non-zero.
7. On success, records rollback success in release registry.

## Release Registry Integration
Release metadata is persisted in control-plane DB table `releases` through:
- `scripts/release-registry.sh upsert ...`
- `scripts/release-registry.sh list`
- `scripts/release-registry.sh get --release-id <release_id>`

API query surface:
- `GET /api/releases`
- `GET /api/releases/{release_id}`

## Runtime Path Contract
systemd services execute from `/srv/oroboros/current/*` so symlink switch changes active code without in-place mutations:
- API: `/srv/oroboros/current/backend`
- Worker: `/srv/oroboros/current/worker`
- Web surfaces: `/srv/oroboros/current/infra/web-*`

## Optional environment overrides
- `REPO_ROOT`
- `DEPLOY_ROOT`
- `DEPLOY_RELEASES_DIR`
- `DEPLOY_CURRENT_LINK`
- `DEPLOY_SERVICES`
- `DEPLOY_HEALTHCHECK_CMD`
- `DEPLOY_SKIP_SERVICE_RESTART=1`
- `DEPLOY_SKIP_HEALTHCHECK=1`

These are for operational flexibility and local validation only; standard production flow should use defaults.
