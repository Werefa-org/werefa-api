"""FR-05: liveness contact tracking + spot holds.

Adds the columns behind the two-stage flag (``liveness_last_seen_at``,
``liveness_misses``) and the hold action (``liveness_hold_until``,
``liveness_hold_count``), plus the ``liveness_hold`` notification kind.

Revision ID: d4e5f6a7b8c9
Revises: a7c3d9e2f184
Create Date: 2026-07-29

"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "a7c3d9e2f184"
branch_labels = None
depends_on = None

_KINDS_BEFORE = (
    "'head_to_counter', 'you_are_next', 'liveness_ping_request', "
    "'now_serving', 'liveness_stale', 'line_chat_update', 'queue_cleared'"
)
_KINDS_AFTER = _KINDS_BEFORE + ", 'liveness_hold'"


def upgrade() -> None:
    op.add_column(
        "queue_entry",
        sa.Column("liveness_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column(
            "liveness_misses",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "queue_entry",
        sa.Column("liveness_hold_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "queue_entry",
        sa.Column(
            "liveness_hold_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("queue_entry", "liveness_misses", server_default=None)
    op.alter_column("queue_entry", "liveness_hold_count", server_default=None)

    # Call-next scans waiting tickets filtered on the hold column; keep that
    # lookup on an index rather than a sequential scan per call.
    op.create_index(
        "ix_queue_entry_line_hold",
        "queue_entry",
        ["service_item_id", "status", "liveness_hold_until"],
        unique=False,
    )

    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        f"kind IN ({_KINDS_AFTER})",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification WHERE kind = 'liveness_hold'"
    )
    op.drop_constraint("ck_notification_kind", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_kind",
        "notification",
        f"kind IN ({_KINDS_BEFORE})",
    )
    op.drop_index("ix_queue_entry_line_hold", table_name="queue_entry")
    op.drop_column("queue_entry", "liveness_hold_count")
    op.drop_column("queue_entry", "liveness_hold_until")
    op.drop_column("queue_entry", "liveness_misses")
    op.drop_column("queue_entry", "liveness_last_seen_at")
