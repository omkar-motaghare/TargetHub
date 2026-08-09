"""add agent enrollment and credentials

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}

    for name, column in (
        ("credential_hash", sa.Column("credential_hash", sa.String(length=64), nullable=True)),
        ("credential_prefix", sa.Column("credential_prefix", sa.String(length=16), nullable=True)),
        ("credential_created_at", sa.Column("credential_created_at", sa.DateTime(timezone=True), nullable=True)),
        ("credential_revoked_at", sa.Column("credential_revoked_at", sa.DateTime(timezone=True), nullable=True)),
    ):
        if name not in agent_columns:
            op.add_column("agents", column)

    inspector = inspect(bind)
    if not any(index["name"] == "ix_agents_credential_hash" for index in inspector.get_indexes("agents")):
        op.create_index("ix_agents_credential_hash", "agents", ["credential_hash"], unique=True)

    if "agent_enrollments" not in inspector.get_table_names():
        op.create_table(
            "agent_enrollments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("agent_name", sa.String(length=100), nullable=False),
            sa.Column("deployment_scenario", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("agent_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_agent_enrollments_token_hash", "agent_enrollments", ["token_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_enrollments" in inspector.get_table_names():
        op.drop_index("ix_agent_enrollments_token_hash", table_name="agent_enrollments")
        op.drop_table("agent_enrollments")

    inspector = inspect(bind)
    if any(index["name"] == "ix_agents_credential_hash" for index in inspector.get_indexes("agents")):
        op.drop_index("ix_agents_credential_hash", table_name="agents")

    columns = {column["name"] for column in inspector.get_columns("agents")}
    for name in ("credential_revoked_at", "credential_created_at", "credential_prefix", "credential_hash"):
        if name in columns:
            op.drop_column("agents", name)
