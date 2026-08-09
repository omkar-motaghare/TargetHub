"""add agents and capability resource links

Revision ID: a1b2c3d4e5f6
Revises: 8f2c4d6e1a77
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "8f2c4d6e1a77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "agent_resources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("resource_key", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_resources_agent_id", "agent_resources", ["agent_id"])
    op.add_column("target_capabilities", sa.Column("agent_id", sa.String(length=36), nullable=True))
    op.add_column("target_capabilities", sa.Column("resource_id", sa.String(length=36), nullable=True))
    op.create_index("ix_target_capabilities_agent_id", "target_capabilities", ["agent_id"])
    op.create_index("ix_target_capabilities_resource_id", "target_capabilities", ["resource_id"])
    op.create_foreign_key("fk_target_capabilities_agent", "target_capabilities", "agents", ["agent_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_target_capabilities_resource", "target_capabilities", "agent_resources", ["resource_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_target_capabilities_resource", "target_capabilities", type_="foreignkey")
    op.drop_constraint("fk_target_capabilities_agent", "target_capabilities", type_="foreignkey")
    op.drop_index("ix_target_capabilities_resource_id", table_name="target_capabilities")
    op.drop_index("ix_target_capabilities_agent_id", table_name="target_capabilities")
    op.drop_column("target_capabilities", "resource_id")
    op.drop_column("target_capabilities", "agent_id")
    op.drop_index("ix_agent_resources_agent_id", table_name="agent_resources")
    op.drop_table("agent_resources")
    op.drop_table("agents")
