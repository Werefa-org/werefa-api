"""Add provider.region for discovery filters.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider",
        sa.Column("region", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_provider_region", "provider", ["region"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_provider_region", table_name="provider")
    op.drop_column("provider", "region")
