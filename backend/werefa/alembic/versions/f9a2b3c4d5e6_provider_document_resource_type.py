"""Add Cloudinary resource_type on provider_document.

Revision ID: f9a2b3c4d5e6
Revises: c3d4e5f6a789
Create Date: 2026-05-24

"""

import sqlalchemy as sa
from alembic import op

revision = "f9a2b3c4d5e6"
down_revision = "c3d4e5f6a789"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_document",
        sa.Column("resource_type", sa.String(length=16), nullable=False, server_default="raw"),
    )
    op.alter_column("provider_document", "resource_type", server_default=None)


def downgrade() -> None:
    op.drop_column("provider_document", "resource_type")
