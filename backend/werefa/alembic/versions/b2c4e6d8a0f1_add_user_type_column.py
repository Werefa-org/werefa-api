"""Add user.user_type for customer / provider / admin accounts.

Revision ID: b2c4e6d8a0f1
Revises: c7f8a2b91d3e
Create Date: 2026-04-23

"""

import sqlalchemy as sa
from alembic import op

revision = "b2c4e6d8a0f1"
down_revision = "c7f8a2b91d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "user_type",
            sa.String(length=32),
            nullable=False,
            server_default="customer",
        ),
    )
    op.execute(
        sa.text("UPDATE \"user\" SET user_type = 'admin' WHERE is_superuser IS TRUE")
    )


def downgrade() -> None:
    op.drop_column("user", "user_type")
