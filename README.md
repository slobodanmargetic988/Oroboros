# Ouroboros

An app that builds itself. 
Ouroboros is a full-stack monorepo for building and operating the Codex Builder Core MVP. It combines a web app, API, background worker, and host-level runtime automation into one deployable system.

The project is structured to support local development, preview environments, and repeatable production-style deployments with operational guardrails.

It is for now a fun project to showcase the vibecoding capabilites that can be achieved using agents and flow defined in my other project https://github.com/slobodanmargetic988/Agents

## Support This Project
Sponsor on GitHub: [github.com/sponsors/slobodanmargetic988](https://github.com/sponsors/slobodanmargetic988)

## What This Repo Includes
- `frontend/`: Vue 3 + Vite + TypeScript user interface.
- `backend/`: FastAPI service with SQLAlchemy + Alembic for API and data workflows.
- `worker/`: Python worker runtime for background jobs and async processing.
- `infra/`: Runtime topology and host integration (`systemd`, reverse proxy, web placeholders).
- `scripts/`: Operational and developer automation scripts.
- `docs/`: Architecture, contracts, runbooks, and deployment references.

## Project Focus
- Clear separation of runtime boundaries between UI, API, and worker components.
- Deterministic deployment flow using commit-based release switching.
- Preview/runtime validation through smoke and end-to-end checks.
- Operations-first tooling for health checks, rollback handling, and runbook-driven maintenance.

## Quick Start
1. Create environment files:
   - `cp .env.example .env`
   - `cp backend/.env.example backend/.env`
   - `cp worker/.env.example worker/.env`
2. Bootstrap database schema and seed data:
   - `./scripts/db-bootstrap.sh`
3. Install runtime unit files and environment templates:
   - `./scripts/systemd-install-runtime.sh`
4. Deploy a specific commit (creates `/srv/oroboros/current`):
   - `./scripts/deploy.sh <commit_sha>`
5. Start the runtime topology:
   - `./scripts/runtime-up.sh`
6. Run service health checks:
   - `./scripts/runtime-health-check.sh`
7. Run preview smoke/E2E checks:
   - `./scripts/preview-smoke-e2e.sh --preview-url <preview_url>`
8. Continue with local development and operational docs:
   - `docs/local-development.md`
   - `docs/runtime-topology.md`
   - `docs/deployment-flow.md`
   - `docs/fullstack-preview-ops-runbook.md`
   - `docs/preview-smoke-e2e-harness.md`
   - `docs/mvp-go-live-checklist.md`

## Sponsors
<!-- sponsors --><!-- sponsors -->
