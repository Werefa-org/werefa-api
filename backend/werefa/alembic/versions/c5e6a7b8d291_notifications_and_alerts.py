"""Phase 10: notification ledger + user prefs + queue alert idempotency.

Revision ID: c5e6a7b8d291
Revises: aa92d4f80c17
Create Date: 2026-04-30

"""

import sqlalchemy as sa
from alembic import op

revision = "c5e6a7b8d291"
down_revision = "aa92d4f80c17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User-level preference list. JSONB so we can index/inspect later if
    # needed without forcing an extra join table.
    op.add_column(
        "user",
        sa.Column(
            "notification_prefs",
            sa.JSON(),
            nullable=True,
        ),
    )

    # Idempotency for smart alerts: stores the last position at which the
    # system already alerted for this ticket so we never send the same
    # head-to-counter / you-are-next twice.
    op.add_column(
        "queue_entry",
        sa.Column(
            "last_alert_position",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('head_to_counter','you_are_next')",
            name="ck_notification_kind",
        ),
        sa.CheckConstraint(
            "channel IN ('websocket','email','logger')",
            name="ck_notification_channel",
        ),
        sa.CheckConstraint(
            "status IN ('delivered','failed','skipped')",
            name="ck_notification_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["queue_entry.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_user_id"),
        "notification",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_ticket_id"),
        "notification",
        ["ticket_id"],
        unique=False,
    )
    # Recent-first reads for ``GET /me/notifications`` are the dominant
    # query — composite index removes the extra sort step.
    op.create_index(
        "ix_notification_user_created_at",
        "notification",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_user_created_at", table_name="notification")
    op.drop_index(
        op.f("ix_notification_ticket_id"), table_name="notification"
    )
    op.drop_index(
        op.f("ix_notification_user_id"), table_name="notification"
    )
    op.drop_table("notification")
    op.drop_column("queue_entry", "last_alert_position")
    op.drop_column("user", "notification_prefs")
