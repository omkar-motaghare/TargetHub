"""remove agent deployment scenario

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_enrollments") as batch_op:
        batch_op.drop_column("deployment_scenario")


def downgrade() -> None:
    with op.batch_alter_table("agent_enrollments") as batch_op:
        batch_op.add_column(
            sa.Column("deployment_scenario", sa.String(length=32), nullable=True)
        )
