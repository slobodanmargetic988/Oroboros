import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

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
from app.core.preview_slot_contract import assert_preview_slot_database_binding, normalize_slot_id
from app.services.observability import (
    emit_structured_log,
    ensure_trace_id,
    reset_current_trace_id,
    set_current_trace_id,
)

settings = get_settings()
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _validate_preview_slot_runtime_contract() -> None:
    slot_id = os.getenv("SLOT_ID", "").strip()
    if not slot_id:
        return

    canonical_slot = normalize_slot_id(slot_id)
    try:
        expected_db = assert_preview_slot_database_binding(canonical_slot, settings.database_url)
    except ValueError as exc:
        raise RuntimeError(f"preview_slot_database_binding_invalid:{exc}") from exc

    logging.getLogger("app.main").info(
        "preview_slot_runtime_binding slot_id=%s database=%s",
        canonical_slot,
        expected_db,
    )


_validate_preview_slot_runtime_contract()
app = FastAPI(title=settings.app_name)
if settings.cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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
