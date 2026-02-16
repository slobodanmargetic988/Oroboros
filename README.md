# Ouroboros Monorepo Skeleton

This repository contains the initial runtime boundaries for the Codex Builder Core MVP.

## Layout
- `frontend/`: Vue 3 + Vite + TypeScript UI scaffold.
- `backend/`: FastAPI service scaffold with SQLAlchemy session setup.
- `worker/`: Runnable Python worker scaffold for background job processing.
- `infra/`: Host-native runtime topology (`systemd` units + reverse proxy + web placeholders).
- `scripts/`: Local developer helper scripts.
- `docs/`: Technical notes and local operation guides.

## Quick Start
1. Copy shared environment file:
   - `cp .env.example .env`
2. Install runtime unit files and env templates:
   - `./scripts/systemd-install-runtime.sh`
3. Start base runtime topology:
   - `./scripts/runtime-up.sh`
4. Verify all core service health checks:
   - `./scripts/runtime-health-check.sh`
5. Read topology and local guides:
   - `docs/runtime-topology.md`
   - `docs/local-development.md`
