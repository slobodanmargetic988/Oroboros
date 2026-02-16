# Runtime Boundaries

This project is intentionally split into three executable surfaces:

1. `frontend` (Vue/Vite)
   - Browser UI for `/codex` and run review surfaces.
2. `backend` (FastAPI)
   - API boundary for run lifecycle, orchestration metadata, and health endpoints.
3. `worker` (Python service)
   - Background executor boundary for queue-driven orchestration tasks.

Shared concerns are represented by root-level configuration examples (`.env.example`) and script entrypoints under `scripts/`.
