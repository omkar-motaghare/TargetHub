"""add users table and rbac fields

Revision ID: aa11bb22cc33
Revises: b7c8d9e0f1a2
Create Date: 2026-08-17 00:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'aa11bb22cc33'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'users' not in inspector.get_table_names():
        op.create_table(
            'users',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('username', sa.String(length=100), nullable=False, unique=True),
            sa.Column('password_hash', sa.String(length=256), nullable=True),
            sa.Column('roles', sa.String(length=256), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        )
    else:
        cols = [c['name'] for c in inspector.get_columns('users')]
        if 'password_hash' not in cols:
            op.add_column('users', sa.Column('password_hash', sa.String(length=256), nullable=True))
        if 'roles' not in cols:
            op.add_column('users', sa.Column('roles', sa.String(length=256), nullable=True))
        if 'created_at' not in cols:
            op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'users' in inspector.get_table_names():
        cols = [c['name'] for c in inspector.get_columns('users')]
        if 'password_hash' in cols:
            op.drop_column('users', 'password_hash')
        if 'roles' in cols:
            op.drop_column('users', 'roles')
        if 'created_at' in cols:
            op.drop_column('users', 'created_at')