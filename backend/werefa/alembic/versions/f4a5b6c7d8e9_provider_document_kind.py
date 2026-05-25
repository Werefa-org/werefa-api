"""Add document_kind to provider_document.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_document",
        sa.Column(
            "document_kind",
            sa.String(length=32),
            nullable=False,
            server_default="other",
        ),
    )
    op.create_index(
        op.f("ix_provider_document_document_kind"),
        "provider_document",
        ["document_kind"],
        unique=False,
    )
    op.alter_column("provider_document", "document_kind", server_default=None)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_provider_document_document_kind"),
        table_name="provider_document",
    )
    op.drop_column("provider_document", "document_kind")
