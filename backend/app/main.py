from fastapi import FastAPI

from app.api.approvals import router as approvals_router
from app.api.checks import router as checks_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.runs import router as runs_router
from app.api.slots import router as slots_router
from app.api.worktrees import router as worktrees_router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(health_router)
app.include_router(runs_router)
app.include_router(slots_router)
app.include_router(worktrees_router)
app.include_router(events_router)
app.include_router(checks_router)
app.include_router(approvals_router)
