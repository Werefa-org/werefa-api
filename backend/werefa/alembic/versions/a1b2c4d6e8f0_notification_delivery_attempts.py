"""FR-07: record delivery attempts before they reach a gateway.

The delivery worker resolves a ``queued`` row *after* the provider
answers, so a process that dies in between leaves the row ``queued`` with
no way to tell whether the message went out. Startup reconciliation would
then re-send it and the customer gets a second text.

``delivery_attempts`` is the missing evidence. The worker increments and
commits it *before* calling the provider, so ``0`` means the job never
reached a gateway (safe to re-send) and anything higher means it might
have (never re-send, resolve the row instead).

Backfilled to ``0`` rather than ``1``: every row that exists at migration
time is already settled except the zombies this work is about, and those
predate the counter — the first sweep after deploy treats them as
un-attempted. That is the one batch where the old behaviour still applies,
and it is bounded by ``NOTIFICATION_RECONCILE_MAX_AGE_SECONDS``.

Revision ID: a1b2c4d6e8f0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-30

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c4d6e8f0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("notification", "delivery_attempts")
