"""add agents and capability resource links

Revision ID: a1b2c3d4e5f6
Revises: 8f2c4d6e1a77
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "8f2c4d6e1a77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_exists(
    inspector: sa.Inspector,
    table_name: str,
    constraint_name: str,
) -> bool:
    return any(
        foreign_key.get("name") == constraint_name
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _table_exists(inspector, "agents"):
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

    inspector = inspect(bind)

    if not _table_exists(inspector, "agent_resources"):
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

    inspector = inspect(bind)

    if not _index_exists(inspector, "agent_resources", "ix_agent_resources_agent_id"):
        op.create_index("ix_agent_resources_agent_id", "agent_resources", ["agent_id"])

    if not _column_exists(inspector, "target_capabilities", "agent_id"):
        op.add_column(
            "target_capabilities",
            sa.Column("agent_id", sa.String(length=36), nullable=True),
        )

    if not _column_exists(inspector, "target_capabilities", "resource_id"):
        op.add_column(
            "target_capabilities",
            sa.Column("resource_id", sa.String(length=36), nullable=True),
        )

    inspector = inspect(bind)

    if not _index_exists(inspector, "target_capabilities", "ix_target_capabilities_agent_id"):
        op.create_index(
            "ix_target_capabilities_agent_id",
            "target_capabilities",
            ["agent_id"],
        )

    if not _index_exists(inspector, "target_capabilities", "ix_target_capabilities_resource_id"):
        op.create_index(
            "ix_target_capabilities_resource_id",
            "target_capabilities",
            ["resource_id"],
        )

    inspector = inspect(bind)
    agent_fk_exists = _foreign_key_exists(
        inspector,
        "target_capabilities",
        "fk_target_capabilities_agent",
    )
    resource_fk_exists = _foreign_key_exists(
        inspector,
        "target_capabilities",
        "fk_target_capabilities_resource",
    )

    if not agent_fk_exists or not resource_fk_exists:
        with op.batch_alter_table("target_capabilities", recreate="always") as batch_op:
            if not agent_fk_exists:
                batch_op.create_foreign_key(
                    "fk_target_capabilities_agent",
                    "agents",
                    ["agent_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if not resource_fk_exists:
                batch_op.create_foreign_key(
                    "fk_target_capabilities_resource",
                    "agent_resources",
                    ["resource_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "target_capabilities"):
        foreign_keys = {
            foreign_key.get("name")
            for foreign_key in inspector.get_foreign_keys("target_capabilities")
        }
        indexes = {
            index["name"]
            for index in inspector.get_indexes("target_capabilities")
        }
        columns = {
            column["name"]
            for column in inspector.get_columns("target_capabilities")
        }

        if (
            "fk_target_capabilities_resource" in foreign_keys
            or "fk_target_capabilities_agent" in foreign_keys
            or "ix_target_capabilities_resource_id" in indexes
            or "ix_target_capabilities_agent_id" in indexes
            or "resource_id" in columns
            or "agent_id" in columns
        ):
            with op.batch_alter_table("target_capabilities", recreate="always") as batch_op:
                if "fk_target_capabilities_resource" in foreign_keys:
                    batch_op.drop_constraint(
                        "fk_target_capabilities_resource",
                        type_="foreignkey",
                    )
                if "fk_target_capabilities_agent" in foreign_keys:
                    batch_op.drop_constraint(
                        "fk_target_capabilities_agent",
                        type_="foreignkey",
                    )
                if "resource_id" in columns:
                    batch_op.drop_column("resource_id")
                if "agent_id" in columns:
                    batch_op.drop_column("agent_id")

    inspector = inspect(bind)

    if _table_exists(inspector, "agent_resources"):
        op.drop_index("ix_agent_resources_agent_id", table_name="agent_resources") if _index_exists(
            inspector,
            "agent_resources",
            "ix_agent_resources_agent_id",
        ) else None
        op.drop_table("agent_resources")

    inspector = inspect(bind)
    if _table_exists(inspector, "agents"):
        op.drop_table("agents")
