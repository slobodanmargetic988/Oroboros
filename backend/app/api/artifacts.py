from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models import RunArtifact

router = APIRouter(prefix="/api", tags=["artifacts"])


class RunArtifactResponse(BaseModel):
    id: int
    run_id: str
    artifact_type: str
    artifact_uri: str
    metadata: dict | None
    created_at: datetime


@router.get("/runs/{run_id}/artifacts", response_model=list[RunArtifactResponse])
def list_run_artifacts(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> list[RunArtifactResponse]:
    rows = (
        db.query(RunArtifact)
        .filter(RunArtifact.run_id == run_id)
        .order_by(RunArtifact.id.asc())
        .limit(limit)
        .all()
    )
    return [
        RunArtifactResponse(
            id=row.id,
            run_id=row.run_id,
            artifact_type=row.artifact_type,
            artifact_uri=row.artifact_uri,
            metadata=row.metadata_json,
            created_at=row.created_at,
        )
        for row in rows
    ]
