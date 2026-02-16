from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import utcnow


class PreviewDbReset(Base):
    __tablename__ = "preview_db_resets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), index=True)
    slot_id: Mapped[str] = mapped_column(String(32), index=True)
    db_name: Mapped[str] = mapped_column(String(128))
    strategy: Mapped[str] = mapped_column(String(32), index=True)
    seed_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_status: Mapped[str] = mapped_column(String(32), index=True)
    reset_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reset_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
