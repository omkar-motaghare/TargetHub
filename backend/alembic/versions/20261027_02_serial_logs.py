"""serial session transcripts

Revision ID: 20261027_02
Revises: 20261027_01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_02"
down_revision: str | Sequence[str] | None = "20261027_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "serial_log_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["target_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_serial_log_chunks_session_id", "serial_log_chunks", ["session_id"])
    op.create_index("ix_serial_log_chunks_created_at", "serial_log_chunks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_serial_log_chunks_created_at", table_name="serial_log_chunks")
    op.drop_index("ix_serial_log_chunks_session_id", table_name="serial_log_chunks")
    op.drop_table("serial_log_chunks")
