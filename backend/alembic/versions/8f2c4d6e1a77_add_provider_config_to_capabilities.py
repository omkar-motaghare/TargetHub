"""add provider config to target capabilities

Revision ID: 8f2c4d6e1a77
Revises: 5e7a9c1d2f34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c4d6e1a77"
down_revision: str | Sequence[str] | None = "5e7a9c1d2f34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "target_capabilities",
        sa.Column("provider_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("target_capabilities", "provider_config")
