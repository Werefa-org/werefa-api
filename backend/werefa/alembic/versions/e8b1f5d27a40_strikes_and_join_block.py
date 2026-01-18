"""Phase 7: user_strike table + user.joins_blocked_until.

Revision ID: e8b1f5d27a40
Revises: d4f8c1a3b209
Create Date: 2026-04-29

"""

import sqlalchemy as sa
from alembic import op

revision = "e8b1f5d27a40"
down_revision = "d4f8c1a3b209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "joins_blocked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_table(
        "user_strike",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["queue_entry.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["provider.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_strike_user_id"),
        "user_strike",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_strike_ticket_id"),
        "user_strike",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_strike_provider_id"),
        "user_strike",
        ["provider_id"],
        unique=False,
    )
    # Composite index supports the recurring "count strikes for user in window"
    # query without a sort step.
    op.create_index(
        "ix_user_strike_user_created_at",
        "user_strike",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_strike_user_created_at", table_name="user_strike")
    op.drop_index(op.f("ix_user_strike_provider_id"), table_name="user_strike")
    op.drop_index(op.f("ix_user_strike_ticket_id"), table_name="user_strike")
    op.drop_index(op.f("ix_user_strike_user_id"), table_name="user_strike")
    op.drop_table("user_strike")
    op.drop_column("user", "joins_blocked_until")
