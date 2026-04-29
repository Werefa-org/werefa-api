"""Phase 8: queue_entry.serving_started_at for the EWT service-line WMA.

Revision ID: f1a3c9b6e521
Revises: e8b1f5d27a40
Create Date: 2026-04-29

"""

import sqlalchemy as sa
from alembic import op

revision = "f1a3c9b6e521"
down_revision = "e8b1f5d27a40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queue_entry",
        sa.Column(
            "serving_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # No backfill: pre-existing completed tickets have no recorded "serve
    # start" so they are conservatively excluded from the EWT WMA. The
    # algorithm falls back to ``service_item.avg_duration_minutes`` until
    # at least ``EWT_MIN_SAMPLES`` post-migration samples accumulate.


def downgrade() -> None:
    op.drop_column("queue_entry", "serving_started_at")
