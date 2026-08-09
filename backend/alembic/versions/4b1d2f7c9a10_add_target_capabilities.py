"""add target capabilities

Revision ID: 4b1d2f7c9a10
Revises: 978ee9321260
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b1d2f7c9a10"
down_revision: Union[str, Sequence[str], None] = "978ee9321260"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "target_capabilities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("capability_type", sa.String(length=32), nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["targets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id",
            "name",
            name="uq_target_capability_name",
        ),
    )
    op.create_index(
        "ix_target_capabilities_target_id",
        "target_capabilities",
        ["target_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_target_capabilities_target_id",
        table_name="target_capabilities",
    )
    op.drop_table("target_capabilities")
