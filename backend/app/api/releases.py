from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.release_registry import get_release_by_id, list_releases

router = APIRouter(prefix="/api/releases", tags=["releases"])


class ReleaseResponse(BaseModel):
    id: int
    release_id: str
    commit_sha: str
    migration_marker: str | None
    status: str
    deployed_at: datetime | None


def _to_release_response(item) -> ReleaseResponse:
    return ReleaseResponse(
        id=item.id,
        release_id=item.release_id,
        commit_sha=item.commit_sha,
        migration_marker=item.migration_marker,
        status=item.status,
        deployed_at=item.deployed_at,
    )


@router.get("", response_model=list[ReleaseResponse])
def get_releases(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> list[ReleaseResponse]:
    records = list_releases(db=db, limit=limit, status=status)
    return [_to_release_response(item) for item in records]


@router.get("/{release_id}", response_model=ReleaseResponse)
def get_release(release_id: str, db: Session = Depends(get_db_session)) -> ReleaseResponse:
    record = get_release_by_id(db=db, release_id=release_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return _to_release_response(record)
