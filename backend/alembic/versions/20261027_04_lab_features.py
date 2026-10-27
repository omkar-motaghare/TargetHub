"""lab features: target tags/status reason, reservation note/warning, settings, waitlist, notifications

Revision ID: 20261027_04
Revises: 20261027_03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_04"
down_revision: str | Sequence[str] | None = "20261027_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("targets") as batch_op:
        batch_op.add_column(sa.Column("status_reason", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.add_column(sa.Column("note", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("released_by", sa.String(length=100), nullable=True))

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("tag", sa.String(length=64), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reservation_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "target_id", "tag", "status"):
        op.create_index(f"ix_waitlist_entries_{column}", "waitlist_entries", [column])
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("reservation_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    for column in ("user_id", "target_id", "tag", "status"):
        op.drop_index(f"ix_waitlist_entries_{column}", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    op.drop_table("app_settings")
    with op.batch_alter_table("reservations") as batch_op:
        batch_op.drop_column("released_by")
        batch_op.drop_column("warned_at")
        batch_op.drop_column("note")
    with op.batch_alter_table("targets") as batch_op:
        batch_op.drop_column("tags")
        batch_op.drop_column("status_reason")
