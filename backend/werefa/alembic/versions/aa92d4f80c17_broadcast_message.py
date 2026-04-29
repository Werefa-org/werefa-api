"""Phase 9: broadcast_message table.

Revision ID: aa92d4f80c17
Revises: f1a3c9b6e521
Create Date: 2026-04-29

"""

import sqlalchemy as sa
from alembic import op

revision = "aa92d4f80c17"
down_revision = "f1a3c9b6e521"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcast_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("service_item_id", sa.Uuid(), nullable=True),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info','warning','critical')",
            name="ck_broadcast_severity",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["provider.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["service_item_id"],
            ["service_item.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # Idempotency is scoped per provider so two providers can use the
        # same client-generated key without collision. The unique
        # constraint allows multiple NULLs (Postgres treats them as
        # distinct), which is the right semantics: requests without a key
        # are never deduplicated.
        sa.UniqueConstraint(
            "provider_id",
            "idempotency_key",
            name="uq_broadcast_provider_idem_key",
        ),
    )
    op.create_index(
        op.f("ix_broadcast_message_provider_id"),
        "broadcast_message",
        ["provider_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broadcast_message_service_item_id"),
        "broadcast_message",
        ["service_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_broadcast_message_author_user_id"),
        "broadcast_message",
        ["author_user_id"],
        unique=False,
    )
    # Reads on `GET /providers/{id}/broadcasts?since=...` order by
    # ``created_at`` and filter by provider — composite index removes the
    # need for an extra sort step.
    op.create_index(
        "ix_broadcast_provider_created_at",
        "broadcast_message",
        ["provider_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_broadcast_provider_created_at", table_name="broadcast_message")
    op.drop_index(
        op.f("ix_broadcast_message_author_user_id"),
        table_name="broadcast_message",
    )
    op.drop_index(
        op.f("ix_broadcast_message_service_item_id"),
        table_name="broadcast_message",
    )
    op.drop_index(
        op.f("ix_broadcast_message_provider_id"),
        table_name="broadcast_message",
    )
    op.drop_table("broadcast_message")
