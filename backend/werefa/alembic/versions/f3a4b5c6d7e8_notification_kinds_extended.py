"""Extend notification.kind for now_serving, liveness_stale, line_chat_update.

Revision ID: f3a4b5c6d7e8
Revises: e8f4a1b2c3d4
Create Date: 2026-05-24

"""

from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e8f4a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ("
        "'head_to_counter', 'you_are_next', 'liveness_ping_request', "
        "'now_serving', 'liveness_stale', 'line_chat_update'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ('head_to_counter', 'you_are_next', 'liveness_ping_request')",
    )
