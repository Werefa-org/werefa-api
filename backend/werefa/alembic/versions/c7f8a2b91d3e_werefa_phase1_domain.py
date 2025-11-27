"""Werefa phase 1: provider, service, queue domain; drop template item

Revision ID: c7f8a2b91d3e
Revises: fe56fa70289e
Create Date: 2026-04-12

"""

import sqlalchemy as sa
from alembic import op

revision = "c7f8a2b91d3e"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("item")

    op.add_column(
        "user", sa.Column("phone_number", sa.String(length=20), nullable=True)
    )

    op.create_table(
        "provider",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("biz_name", sa.String(length=200), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("join_radius_m", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column("access_code", sa.String(length=6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provider_slug"), "provider", ["slug"], unique=True)

    op.create_table(
        "provider_membership",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "user_id", name="uq_membership_provider_user"),
    )

    op.create_table(
        "service_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("avg_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("next_ticket_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "queue_entry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("guest_name", sa.String(length=100), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["service_item_id"], ["service_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_queue_entry_one_active_user",
        "queue_entry",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND (status)::text IN ('waiting','serving')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_queue_entry_one_active_user", table_name="queue_entry")
    op.drop_table("queue_entry")
    op.drop_table("service_item")
    op.drop_table("provider_membership")
    op.drop_index(op.f("ix_provider_slug"), table_name="provider")
    op.drop_table("provider")

    op.drop_column("user", "phone_number")

    op.create_table(
        "item",
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
