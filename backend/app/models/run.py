from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import utcnow, uuid_str


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slot_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("runs.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_runs_created_at", "created_at"),
    )
