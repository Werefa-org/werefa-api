"""Allow notification.status = 'queued' for off-request delivery.

Channels that leave the machine (SMS, email) are handed to the delivery
worker instead of being sent inside the request, so ``dispatch`` writes
the ledger row before the outcome is known. The worker later rewrites it
as 'delivered' or 'failed'.

Revision ID: a7c3d9e2f184
Revises: f4a5b6c7d8e9
Create Date: 2026-07-29

"""

from alembic import op

revision = "a7c3d9e2f184"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_status", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_status",
        "notification",
        "status IN ('delivered', 'failed', 'skipped', 'queued')",
    )


def downgrade() -> None:
    # Any row still mid-flight has no meaningful pre-'queued' status; call
    # it 'failed' so the narrowed constraint can be applied. Nothing is
    # lost that the worker was not about to overwrite anyway.
    op.execute(
        "UPDATE notification SET status = 'failed' WHERE status = 'queued'"
    )
    op.drop_constraint("ck_notification_status", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_status",
        "notification",
        "status IN ('delivered', 'failed', 'skipped')",
    )
