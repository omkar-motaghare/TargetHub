"""board health checks

Revision ID: 20261028_02
Revises: 20261028_01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261028_02"
down_revision: str | Sequence[str] | None = "20261028_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_health_checks",
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("boot_pattern", sa.String(length=200), nullable=False),
        sa.Column("boot_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("power_operation", sa.String(length=16), nullable=False),
        sa.Column("failure_threshold", sa.Integer(), nullable=False),
        sa.Column("auto_maintenance", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_message", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("maintenance_by_check", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("target_id"),
    )
    op.create_index("ix_target_health_checks_next_run_at", "target_health_checks", ["next_run_at"])
    op.create_table(
        "target_health_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_target_health_results_target_id", "target_health_results", ["target_id"])
    op.create_index("ix_target_health_results_started_at", "target_health_results", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_target_health_results_started_at", table_name="target_health_results")
    op.drop_index("ix_target_health_results_target_id", table_name="target_health_results")
    op.drop_table("target_health_results")
    op.drop_index("ix_target_health_checks_next_run_at", table_name="target_health_checks")
    op.drop_table("target_health_checks")
