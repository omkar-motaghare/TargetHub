"""merge heads and add audit_logs

Revision ID: d4e5f6a7b8c9
Revises: aa11bb22cc33, c1d2e3f4a5b6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = ("aa11bb22cc33", "c1d2e3f4a5b6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("provider_key", sa.String(length=100), nullable=True),
        sa.Column("capability_type", sa.String(length=32), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_target_id", "audit_logs", ["target_id"])
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_session_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_target_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
