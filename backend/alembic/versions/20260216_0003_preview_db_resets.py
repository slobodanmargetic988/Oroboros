"""add preview db reset tracking

Revision ID: 20260216_0003
Revises: 20260216_0002
Create Date: 2026-02-16 13:50:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260216_0003"
down_revision: Union[str, None] = "20260216_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preview_db_resets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("slot_id", sa.String(length=32), nullable=False),
        sa.Column("db_name", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("seed_version", sa.String(length=64), nullable=True),
        sa.Column("snapshot_version", sa.String(length=64), nullable=True),
        sa.Column("reset_status", sa.String(length=32), nullable=False),
        sa.Column("reset_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preview_db_resets_run_id", "preview_db_resets", ["run_id"], unique=False)
    op.create_index("ix_preview_db_resets_slot_id", "preview_db_resets", ["slot_id"], unique=False)
    op.create_index("ix_preview_db_resets_strategy", "preview_db_resets", ["strategy"], unique=False)
    op.create_index("ix_preview_db_resets_reset_status", "preview_db_resets", ["reset_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_preview_db_resets_reset_status", table_name="preview_db_resets")
    op.drop_index("ix_preview_db_resets_strategy", table_name="preview_db_resets")
    op.drop_index("ix_preview_db_resets_slot_id", table_name="preview_db_resets")
    op.drop_index("ix_preview_db_resets_run_id", table_name="preview_db_resets")
    op.drop_table("preview_db_resets")
