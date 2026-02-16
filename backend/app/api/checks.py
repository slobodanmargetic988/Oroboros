from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models import ValidationCheck

router = APIRouter(prefix="/api", tags=["checks"])


class ValidationCheckResponse(BaseModel):
    id: int
    run_id: str
    check_name: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    artifact_uri: str | None


@router.get("/runs/{run_id}/checks", response_model=list[ValidationCheckResponse])
def list_run_checks(
    run_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    db: Session = Depends(get_db_session),
) -> list[ValidationCheckResponse]:
    checks = (
        db.query(ValidationCheck)
        .filter(ValidationCheck.run_id == run_id)
        .order_by(ValidationCheck.id.asc())
        .limit(limit)
        .all()
    )

    return [
        ValidationCheckResponse(
            id=check.id,
            run_id=check.run_id,
            check_name=check.check_name,
            status=check.status,
            started_at=check.started_at,
            ended_at=check.ended_at,
            artifact_uri=check.artifact_uri,
        )
        for check in checks
    ]
