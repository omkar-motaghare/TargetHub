"""add agent operations queue

Revision ID: f0a1b2c3d4e5
Revises: e6a7b8c9d0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("resource_key", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_metadata", sa.JSON(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["target_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["agent_resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_agent_operations_agent_id", "agent_operations", ["agent_id"])
    op.create_index("ix_agent_operations_session_id", "agent_operations", ["session_id"])
    op.create_index("ix_agent_operations_resource_id", "agent_operations", ["resource_id"])
    op.create_index("ix_agent_operations_status", "agent_operations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_operations_status", table_name="agent_operations")
    op.drop_index("ix_agent_operations_resource_id", table_name="agent_operations")
    op.drop_index("ix_agent_operations_session_id", table_name="agent_operations")
    op.drop_index("ix_agent_operations_agent_id", table_name="agent_operations")
    op.drop_table("agent_operations")
