# DB Bootstrap and Migrations

This project uses Alembic for control-plane schema migrations.

## Prerequisites
- Python 3.11+
- Local PostgreSQL running on host (non-container setup)
- `DATABASE_URL` configured (defaults to backend `.env` value)

## Baseline Schema
- Migration root: `backend/alembic/`
- Initial migration: `backend/alembic/versions/20260216_0001_initial_control_plane.py`
- Preview DB reset tracking migration: `backend/alembic/versions/20260216_0003_preview_db_resets.py`

The baseline creates the MVP control-plane entities:
- `users`
- `runs`
- `run_events`
- `run_context`
- `run_artifacts`
- `validation_checks`
- `slot_leases`
- `preview_db_resets`
- `approvals`
- `releases`
- `audit_log`

## One-command Bootstrap (venv + migrate + seed)
```bash
./scripts/db-bootstrap.sh
```

## Run Migrations Only
```bash
./scripts/db-migrate.sh
```

## Seed Local Data Only
```bash
./scripts/db-seed.sh
```

## Local Seed Data
The seed script inserts a deterministic starter dataset:
- user: `dev@ouroboros.local`
- run: one queued run linked to that user
- run context/event and audit entry

Implementation module: `backend/app/db/seed.py`

## Preview Seed Inputs (slot DBs)
Deterministic preview slot seed SQL is versioned under:
- `infra/db/preview/seeds/v1.sql`

Operational wrappers:
- `scripts/preview-db-reset.sh`
- `scripts/preview-db-seed.sh`
- `scripts/preview-db-reset-and-seed.sh`
