# Ouroboros Monorepo Skeleton

This repository contains the initial runtime boundaries for the Codex Builder Core MVP.

## Layout
- `frontend/`: Vue 3 + Vite + TypeScript UI scaffold.
- `backend/`: FastAPI service scaffold with SQLAlchemy session setup.
- `worker/`: Runnable Python worker scaffold for background job processing.
- `scripts/`: Local developer helper scripts.
- `docs/`: Technical notes and local operation guides.

## Quick Start
1. Copy shared environment file:
   - `cp .env.example .env`
2. Follow service-specific setup in:
   - `docs/local-development.md`
3. Optionally use helper scripts:
   - `./scripts/setup-local.sh`
   - `./scripts/run-backend.sh`
   - `./scripts/run-worker.sh`
   - `./scripts/run-frontend.sh`
