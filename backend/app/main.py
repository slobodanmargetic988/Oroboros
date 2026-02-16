import logging
import time

from fastapi import FastAPI, Request

from app.api.artifacts import router as artifacts_router
from app.api.approvals import router as approvals_router
from app.api.checks import router as checks_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.releases import router as releases_router
from app.api.runs import router as runs_router
from app.api.slots import router as slots_router
from app.api.worktrees import router as worktrees_router
from app.core.config import get_settings
from app.services.observability import (
    emit_structured_log,
    ensure_trace_id,
    reset_current_trace_id,
    set_current_trace_id,
)

settings = get_settings()
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def trace_and_request_log_middleware(request: Request, call_next):
    trace_id = ensure_trace_id(request.headers.get("x-trace-id"))
    token = set_current_trace_id(trace_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        path_params = request.scope.get("path_params") or {}
        emit_structured_log(
            component="api",
            event="http_request",
            trace_id=trace_id,
            run_id=path_params.get("run_id") or request.headers.get("x-run-id"),
            slot_id=request.headers.get("x-slot-id"),
            commit_sha=request.headers.get("x-commit-sha"),
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        reset_current_trace_id(token)


app.include_router(health_router)
app.include_router(runs_router)
app.include_router(slots_router)
app.include_router(worktrees_router)
app.include_router(events_router)
app.include_router(checks_router)
app.include_router(metrics_router)
app.include_router(artifacts_router)
app.include_router(approvals_router)
app.include_router(releases_router)
