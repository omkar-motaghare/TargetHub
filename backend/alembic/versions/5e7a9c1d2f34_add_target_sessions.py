"""add target sessions

Revision ID: 5e7a9c1d2f34
Revises: 7c3e1a9f2b44
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e7a9c1d2f34"
down_revision: str | Sequence[str] | None = "7c3e1a9f2b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("capability_type", sa.String(length=32), nullable=False),
        sa.Column("provider_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_target_sessions_reservation_id", "target_sessions", ["reservation_id"])
    op.create_index("ix_target_sessions_target_id", "target_sessions", ["target_id"])
    op.create_index("ix_target_sessions_user_id", "target_sessions", ["user_id"])
    op.create_index("ix_target_sessions_status", "target_sessions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_target_sessions_status", table_name="target_sessions")
    op.drop_index("ix_target_sessions_user_id", table_name="target_sessions")
    op.drop_index("ix_target_sessions_target_id", table_name="target_sessions")
    op.drop_index("ix_target_sessions_reservation_id", table_name="target_sessions")
    op.drop_table("target_sessions")
