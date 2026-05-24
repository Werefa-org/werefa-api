"""Join approval, guest contact fields, provider customer blocks.

Revision ID: c1d2e3f4a5b6
Revises: a9b8c7d6e5f4
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_item",
        sa.Column(
            "requires_join_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "service_item",
        sa.Column(
            "approval_queue_order",
            sa.String(length=32),
            nullable=False,
            server_default="preserve_register_time",
        ),
    )
    op.add_column(
        "queue_entry",
        sa.Column("guest_phone", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column("guest_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_queue_entry_approved_by_user_id",
        "queue_entry",
        "user",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "provider_customer_block",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["blocked_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "user_id", name="uq_provider_customer_block"),
    )
    op.drop_index("ix_queue_entry_one_active_user", table_name="queue_entry")
    op.create_index(
        "ix_queue_entry_one_active_user",
        "queue_entry",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND (status)::text IN "
            "('waiting','serving','pending_approval')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_queue_entry_one_active_user", table_name="queue_entry")
    op.create_index(
        "ix_queue_entry_one_active_user",
        "queue_entry",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "user_id IS NOT NULL AND (status)::text IN ('waiting','serving')"
        ),
    )
    op.drop_table("provider_customer_block")
    op.drop_constraint("fk_queue_entry_approved_by_user_id", "queue_entry", type_="foreignkey")
    op.drop_column("queue_entry", "approved_by_user_id")
    op.drop_column("queue_entry", "approved_at")
    op.drop_column("queue_entry", "guest_email")
    op.drop_column("queue_entry", "guest_phone")
    op.drop_column("service_item", "approval_queue_order")
    op.drop_column("service_item", "requires_join_approval")
