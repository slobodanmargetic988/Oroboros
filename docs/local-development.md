# Local Development

## Prerequisites
- Node.js 20+
- Python 3.11+
- Docker + Docker Compose plugin

## 1) Shared Environment
```bash
cp .env.example .env
```

## 2) Runtime Topology (recommended for MYO-15)
```bash
./scripts/runtime-up.sh
./scripts/runtime-health-check.sh
```

Stop runtime stack:
```bash
./scripts/runtime-down.sh
```

## 3) Service-by-service mode (optional)

### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
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

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Health checks
- API: `http://127.0.0.1:8000/health`
- Worker: `http://127.0.0.1:8090/health`
- Reverse proxy health through host routing:
  - `curl -H 'Host: app.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview1.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview2.example.com' http://127.0.0.1:8088/health`
  - `curl -H 'Host: preview3.example.com' http://127.0.0.1:8088/health`
