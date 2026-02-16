from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.metrics_export import collect_core_metrics

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/core")
def get_core_metrics(db: Session = Depends(get_db_session)) -> dict[str, object]:
    return collect_core_metrics(db)
