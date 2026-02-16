from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Release
from app.models.common import utcnow


def list_releases(
    *,
    db: Session,
    limit: int = 100,
    status: str | None = None,
) -> list[Release]:
    query = db.query(Release)
    if status:
        query = query.filter(Release.status == status)
    return query.order_by(Release.id.desc()).limit(limit).all()


def get_release_by_id(*, db: Session, release_id: str) -> Release | None:
    return db.query(Release).filter(Release.release_id == release_id).first()


def upsert_release(
    *,
    db: Session,
    release_id: str,
    commit_sha: str,
    status: str,
    migration_marker: str | None = None,
    deployed_at: datetime | None = None,
) -> Release:
    release = get_release_by_id(db=db, release_id=release_id)
    if release is None:
        release = Release(
            release_id=release_id,
            commit_sha=commit_sha,
            migration_marker=migration_marker,
            status=status,
            deployed_at=deployed_at,
        )
        db.add(release)
    else:
        release.commit_sha = commit_sha
        release.status = status
        if migration_marker is not None:
            release.migration_marker = migration_marker
        if deployed_at is not None:
            release.deployed_at = deployed_at

    if release.deployed_at is None and status in {"deployed", "rolled_back"}:
        release.deployed_at = utcnow()

    db.commit()
    db.refresh(release)
    return release
