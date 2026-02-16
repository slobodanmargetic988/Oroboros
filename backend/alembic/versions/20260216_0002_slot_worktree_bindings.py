"""add slot worktree bindings table

Revision ID: 20260216_0002
Revises: 20260216_0001
Create Date: 2026-02-16 12:45:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260216_0002"
down_revision: Union[str, None] = "20260216_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slot_worktree_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slot_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("worktree_path", sa.String(length=512), nullable=True),
        sa.Column("binding_state", sa.String(length=32), nullable=False),
        sa.Column("last_action", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_slot_worktree_bindings_slot_id",
        "slot_worktree_bindings",
        ["slot_id"],
        unique=True,
    )
    op.create_index(
        "ix_slot_worktree_bindings_run_id",
        "slot_worktree_bindings",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_slot_worktree_bindings_binding_state",
        "slot_worktree_bindings",
        ["binding_state"],
        unique=False,
    )
    op.create_index(
        "ix_slot_worktree_bindings_last_action",
        "slot_worktree_bindings",
        ["last_action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_slot_worktree_bindings_last_action", table_name="slot_worktree_bindings")
    op.drop_index("ix_slot_worktree_bindings_binding_state", table_name="slot_worktree_bindings")
    op.drop_index("ix_slot_worktree_bindings_run_id", table_name="slot_worktree_bindings")
    op.drop_index("ix_slot_worktree_bindings_slot_id", table_name="slot_worktree_bindings")
    op.drop_table("slot_worktree_bindings")
