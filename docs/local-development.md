# Local Development

## Prerequisites
- Node.js 20+
- Python 3.11+
- Caddy installed on host
- PostgreSQL installed on host
- Redis installed on host
- systemd-enabled Linux host

## 1) Shared Environment
```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp worker/.env.example worker/.env
```

## 2) Bootstrap backend DB (schema + seed)
```bash
./scripts/db-bootstrap.sh
```

Details: `docs/db-bootstrap-and-migrations.md`

## 3) Install and start runtime services (systemd)
```bash
./scripts/systemd-install-runtime.sh
./scripts/preview-slots-provision.sh
./scripts/runtime-up.sh
./scripts/runtime-health-check.sh
```

Stop runtime stack:
```bash
./scripts/runtime-down.sh
```

Preview slot-only health checks:
```bash
./scripts/preview-slots-health-check.sh
```

Allocate one preview slot for a run (includes DB reset + seed flow):
```bash
./scripts/preview-slot-allocate.sh --run-id <run_id> --seed-version v1 --strategy seed
```

Dry-run DB reset/seed command for a slot:
```bash
./scripts/preview-db-reset-and-seed.sh --slot preview1 --run-id dry-run --strategy seed --seed-version v1 --dry-run
```

## 4) Optional service-by-service mode

### Backend
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Worker
```bash
cd worker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m worker.main
```

### Web surface (example)
```bash
python3 scripts/run-web-surface.py --root infra/web-main --port 3100
```

## Health checks
- API: `http://127.0.0.1:8000/health`
- Worker: `http://127.0.0.1:8090/health`
- Reverse proxy host-routing checks:
  - `curl -H 'Host: app.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview1.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview2.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview3.example.com' http://127.0.0.1:8088/health`
