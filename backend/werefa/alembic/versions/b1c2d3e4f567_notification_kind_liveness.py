"""Allow liveness_ping_request on notification.kind (FR-05).

Revision ID: b1c2d3e4f567
Revises: a7b8c9d0e123
Create Date: 2026-05-11

"""

from alembic import op

revision = "b1c2d3e4f567"
down_revision = "a7b8c9d0e123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ('head_to_counter', 'you_are_next', 'liveness_ping_request')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        "kind IN ('head_to_counter', 'you_are_next')",
    )
