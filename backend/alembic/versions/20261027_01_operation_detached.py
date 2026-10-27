"""agent operations detached flag; agent version/platform

Revision ID: 20261027_01
Revises: f0a1b2c3d4e5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_01"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_operations") as batch_op:
        batch_op.add_column(
            sa.Column("detached", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("agent_version", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("platform", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("platform")
        batch_op.drop_column("agent_version")
    with op.batch_alter_table("agent_operations") as batch_op:
        batch_op.drop_column("detached")
