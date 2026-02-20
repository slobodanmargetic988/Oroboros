# Ouroboros Monorepo Skeleton

This repository contains the initial runtime boundaries for the Codex Builder Core MVP.

## Layout
- `frontend/`: Vue 3 + Vite + TypeScript UI scaffold.
- `backend/`: FastAPI service scaffold with SQLAlchemy session setup + Alembic migrations.
- `worker/`: Runnable Python worker scaffold for background job processing.
- `infra/`: Host-native runtime topology (`systemd` units + reverse proxy + web placeholders).
- `scripts/`: Local developer helper scripts.
- `docs/`: Technical notes and local operation guides.

## Quick Start
1. Copy shared environment files:
   - `cp .env.example .env`
   - `cp backend/.env.example backend/.env`
   - `cp worker/.env.example worker/.env`
2. Bootstrap DB schema and local seed data:
   - `./scripts/db-bootstrap.sh`
3. Install runtime unit files and env templates:
   - `./scripts/systemd-install-runtime.sh`
4. Deploy an exact commit with atomic release switch (creates `/srv/oroboros/current`):
   - `./scripts/deploy.sh <commit_sha>`
5. Start base runtime topology:
   - `./scripts/runtime-up.sh`
6. Verify core service health checks:
   - `./scripts/runtime-health-check.sh`
7. Run preview smoke/E2E harness (headless):
   - `./scripts/preview-smoke-e2e.sh --preview-url <preview_url>`
8. Read topology and operation guides:
   - `docs/public-user-guide.html`
   - `docs/faq.html`
   - `docs/developer-architecture-guide.html`
   - `docs/configuration-guide.html`
   - `docs/platform-prerequisites-guide.html`
   - `docs/database-usage-guide.html`
   - `docs/runtime-topology.md`
   - `docs/deployment-flow.md`
   - `docs/fullstack-preview-slot-runtime-contract.md`
   - `docs/preview-runtime-slots.md`
   - `docs/preview-smoke-e2e-harness.md`
   - `docs/worker-security-guardrails.md`
   - `docs/operator-incident-rollback-runbook.md`
   - `docs/mvp-go-live-checklist.md`
   - `docs/db-bootstrap-and-migrations.md`
   - `docs/run-state-machine-contract.md`
   - `docs/slot-lease-manager-contract.md`
   - `docs/git-worktree-manager-contract.md`
   - `docs/local-development.md`
