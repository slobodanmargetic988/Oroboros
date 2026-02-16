# DB Bootstrap and Migrations

This project uses Alembic for control-plane schema migrations.

## Prerequisites
- Python 3.11+
- Local PostgreSQL running on host (non-container setup)
- `DATABASE_URL` configured (defaults to backend `.env` value)

## Baseline Schema
- Migration root: `backend/alembic/`
- Initial migration: `backend/alembic/versions/20260216_0001_initial_control_plane.py`

The baseline creates the MVP control-plane entities:
- `users`
- `runs`
- `run_events`
- `run_context`
- `run_artifacts`
- `validation_checks`
- `slot_leases`
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
