"""teams and team-restricted targets

Revision ID: 20261125_01
Revises: 20261028_02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261125_01"
down_revision: str | Sequence[str] | None = "20261028_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id", "username"),
    )
    op.create_index("ix_team_members_username", "team_members", ["username"])
    op.create_table(
        "team_targets",
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id", "target_id"),
    )
    op.create_index("ix_team_targets_target_id", "team_targets", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_team_targets_target_id", table_name="team_targets")
    op.drop_table("team_targets")
    op.drop_index("ix_team_members_username", table_name="team_members")
    op.drop_table("team_members")
    op.drop_table("teams")
