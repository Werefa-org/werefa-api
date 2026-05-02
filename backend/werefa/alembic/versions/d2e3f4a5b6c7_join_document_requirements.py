"""Join document requirements on service lines + ticket uploads.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_item",
        sa.Column(
            "requires_join_documents",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "service_item",
        sa.Column("join_document_requirements", sa.JSON(), nullable=True),
    )
    op.create_table(
        "ticket_join_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("storage_relpath", sa.String(length=500), nullable=False),
        sa.Column("resource_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["queue_entry.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_join_document_ticket_id",
        "ticket_join_document",
        ["ticket_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_join_document_ticket_id", table_name="ticket_join_document")
    op.drop_table("ticket_join_document")
    op.drop_column("service_item", "join_document_requirements")
    op.drop_column("service_item", "requires_join_documents")
