"""Phase 6: review table + provider rating counters.

Revision ID: d4f8c1a3b209
Revises: b2c4e6d8a0f1
Create Date: 2026-04-29

"""

import sqlalchemy as sa
from alembic import op

revision = "d4f8c1a3b209"
down_revision = "b2c4e6d8a0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provider aggregate counters. server_default keeps the column NOT NULL
    # for existing rows; SQLModel-side default keeps new inserts at 0.
    op.add_column(
        "provider",
        sa.Column(
            "ratings_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "provider",
        sa.Column(
            "ratings_sum", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "provider",
        sa.Column(
            "estimate_accurate_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("was_estimate_accurate", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5", name="ck_review_rating_1_5"
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["queue_entry.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["provider.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["service_item_id"], ["service_item.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id", name="uq_review_ticket"),
    )
    op.create_index(
        op.f("ix_review_ticket_id"), "review", ["ticket_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_user_id"), "review", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_provider_id"), "review", ["provider_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_service_item_id"),
        "review",
        ["service_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_review_service_item_id"), table_name="review")
    op.drop_index(op.f("ix_review_provider_id"), table_name="review")
    op.drop_index(op.f("ix_review_user_id"), table_name="review")
    op.drop_index(op.f("ix_review_ticket_id"), table_name="review")
    op.drop_table("review")
    op.drop_column("provider", "estimate_accurate_count")
    op.drop_column("provider", "ratings_sum")
    op.drop_column("provider", "ratings_count")
