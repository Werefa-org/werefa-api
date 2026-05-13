"""Phase 11: liveness (FR-05) — position pings + queue_entry liveness columns.

Revision ID: a7b8c9d0e123
Revises: c5e6a7b8d291
Create Date: 2026-05-11

"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e123"
down_revision = "c5e6a7b8d291"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_ping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Integer(), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["queue_entry.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_position_ping_ticket_sent_at",
        "position_ping",
        ["ticket_id", "sent_at"],
        unique=False,
    )

    op.add_column(
        "queue_entry",
        sa.Column(
            "liveness_state",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "queue_entry",
        sa.Column("liveness_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("queue_entry", "liveness_state", server_default=None)


def downgrade() -> None:
    op.drop_column("queue_entry", "liveness_deadline_at")
    op.drop_column("queue_entry", "liveness_state")
    op.drop_index("ix_position_ping_ticket_sent_at", table_name="position_ping")
    op.drop_table("position_ping")
