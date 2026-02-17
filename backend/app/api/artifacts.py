from __future__ import annotations

from datetime import datetime
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.models import Run, RunArtifact, ValidationCheck

router = APIRouter(prefix="/api", tags=["artifacts"])


class RunArtifactResponse(BaseModel):
    id: int
    run_id: str
    artifact_type: str
    artifact_uri: str
    metadata: dict | None
    created_at: datetime


def _artifact_roots() -> list[Path]:
    roots = [(Path(__file__).resolve().parents[3] / "artifacts").resolve()]
    configured = os.getenv("WORKER_ARTIFACT_ROOT", "").strip()
    if configured:
        roots.append(Path(configured).expanduser().resolve())

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _artifact_path_from_uri(uri: str) -> Path | None:
    value = uri.strip()
    if not value:
        return None

    if value.startswith("file://"):
        parsed = urlparse(value)
        if not parsed.path:
            return None
        return Path(parsed.path).expanduser().resolve()

    if value.startswith("/"):
        return Path(value).expanduser().resolve()

    return None


def _is_within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


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


@router.get("/runs/{run_id}/artifacts/content")
def get_run_artifact_content(
    run_id: str,
    uri: str = Query(..., min_length=1),
    db: Session = Depends(get_db_session),
):
    run = db.query(Run).filter(Run.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")

    linked = (
        db.query(RunArtifact.id)
        .filter(RunArtifact.run_id == run_id, RunArtifact.artifact_uri == uri)
        .first()
    )
    if linked is None:
        linked = (
            db.query(ValidationCheck.id)
            .filter(ValidationCheck.run_id == run_id, ValidationCheck.artifact_uri == uri)
            .first()
        )
    if linked is None:
        raise HTTPException(status_code=404, detail="artifact_not_linked_to_run")

    path = _artifact_path_from_uri(uri)
    if path is None:
        raise HTTPException(status_code=422, detail="unsupported_artifact_uri")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact_file_not_found")

    roots = _artifact_roots()
    if not any(_is_within_root(path, root) for root in roots):
        raise HTTPException(status_code=403, detail="artifact_path_not_allowed")

    guessed = mimetypes.guess_type(path.name)[0] or "text/plain"
    return FileResponse(path=str(path), media_type=guessed)
