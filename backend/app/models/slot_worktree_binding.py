from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import utcnow


class SlotWorktreeBinding(Base):
    __tablename__ = "slot_worktree_bindings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("runs.id"), nullable=True, index=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    binding_state: Mapped[str] = mapped_column(String(32), index=True, default="active")
    last_action: Mapped[str] = mapped_column(String(64), index=True, default="assigned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
