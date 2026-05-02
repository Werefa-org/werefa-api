"""Clear-queue: line_chat_cleared_at, queue_entry.close_reason.

Revision ID: a9b8c7d6e5f4
Revises: f3a4b5c6d7e8
Create Date: 2026-05-24

"""

import sqlalchemy as sa
from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_item",
        sa.Column("line_chat_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column("close_reason", sa.String(length=32), nullable=True),
    )
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ("
        "'head_to_counter', 'you_are_next', 'liveness_ping_request', "
        "'now_serving', 'liveness_stale', 'line_chat_update', 'queue_cleared'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ("
        "'head_to_counter', 'you_are_next', 'liveness_ping_request', "
        "'now_serving', 'liveness_stale', 'line_chat_update'"
        ")",
    )
    op.drop_column("queue_entry", "close_reason")
    op.drop_column("service_item", "line_chat_cleared_at")
