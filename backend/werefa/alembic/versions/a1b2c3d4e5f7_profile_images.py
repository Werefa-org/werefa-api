"""Profile image fields on user and provider.

Revision ID: a1b2c3d4e5f7
Revises: f9a2b3c4d5e6
Create Date: 2026-05-24

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "f9a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("profile_image_public_id", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("profile_image_resource_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "provider",
        sa.Column("profile_image_public_id", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "provider",
        sa.Column("profile_image_resource_type", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider", "profile_image_resource_type")
    op.drop_column("provider", "profile_image_public_id")
    op.drop_column("user", "profile_image_resource_type")
    op.drop_column("user", "profile_image_public_id")
