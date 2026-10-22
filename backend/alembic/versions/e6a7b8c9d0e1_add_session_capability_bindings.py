"""add session capability bindings

Revision ID: e6a7b8c9d0e1
Revises: d4e5f6a7b8c9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ON_DELETE_SET_NULL = "SET NULL"


def upgrade() -> None:
    with op.batch_alter_table("target_sessions") as batch_op:
        batch_op.add_column(sa.Column("capability_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("agent_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("resource_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_target_sessions_capability",
            "target_capabilities",
            ["capability_id"],
            ["id"],
            ondelete=ON_DELETE_SET_NULL,
        )
        batch_op.create_foreign_key(
            "fk_target_sessions_agent",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete=ON_DELETE_SET_NULL,
        )
        batch_op.create_foreign_key(
            "fk_target_sessions_resource",
            "agent_resources",
            ["resource_id"],
            ["id"],
            ondelete=ON_DELETE_SET_NULL,
        )

    op.create_index("ix_target_sessions_capability_id", "target_sessions", ["capability_id"])
    op.create_index("ix_target_sessions_agent_id", "target_sessions", ["agent_id"])
    op.create_index("ix_target_sessions_resource_id", "target_sessions", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_target_sessions_resource_id", table_name="target_sessions")
    op.drop_index("ix_target_sessions_agent_id", table_name="target_sessions")
    op.drop_index("ix_target_sessions_capability_id", table_name="target_sessions")

    with op.batch_alter_table("target_sessions") as batch_op:
        batch_op.drop_constraint("fk_target_sessions_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_target_sessions_agent", type_="foreignkey")
        batch_op.drop_constraint("fk_target_sessions_capability", type_="foreignkey")
        batch_op.drop_column("resource_id")
        batch_op.drop_column("agent_id")
        batch_op.drop_column("capability_id")