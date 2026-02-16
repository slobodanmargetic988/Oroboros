# Local Development

## Prerequisites
- Node.js 20+
- Python 3.11+
- PostgreSQL 15+
- Redis 7+

## 1) Shared Environment
```bash
cp .env.example .env
```

## 2) Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 3) Worker
```bash
cd worker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m worker.main
```

## 4) Frontend
```bash
cd frontend
npm install
npm run dev
```

## Health checks
- Backend: `http://127.0.0.1:8000/health`
- Worker: observe heartbeat logs in terminal every poll cycle
- Frontend: `http://127.0.0.1:5173`
