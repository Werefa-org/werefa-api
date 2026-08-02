"""FR-07: let the ledger say 'accepted' without claiming 'arrived'.

An SMS row was written ``delivered`` the moment Twilio returned a 201.
That is Twilio agreeing to queue the message; the carrier's verdict comes
later, on a status callback nobody was asking for. So a text to a
disconnected number and one the customer acted on produced identical
rows, and FR-05 liveness — which flags customers for not answering
prompts — was reading our own optimism back as proof they had been
warned.

Three changes, all additive:

* ``status`` may now be ``'sent'``: the gateway took it and owes us a
  receipt. Terminal states are unchanged; the receipt moves the row to
  ``delivered`` or ``failed``.
* ``provider_message_id`` — the vendor's id (Twilio's ``MessageSid``),
  recorded when a receipt arrives so a row is traceable in their console.
  Not indexed: rows are correlated by the id we put in the callback URL,
  never looked up by SID, because a fast carrier can report back before
  we have committed the SID.
* ``delivery_error_code`` — why a receipt said failed, which is the
  difference between "their handset was off" and "a carrier is filtering
  us".

Existing rows are untouched. They keep whatever ``delivered`` meant when
they were written, which for SMS is the old optimistic reading — nothing
here can retroactively find out what happened to a message sent last
week, and back-filling ``'sent'`` would strand them waiting for callbacks
that will never come.

Revision ID: b3d5f7a9c024
Revises: a1b2c4d6e8f0
Create Date: 2026-07-30

"""

import sqlalchemy as sa
from alembic import op

revision = "b3d5f7a9c024"
down_revision = "a1b2c4d6e8f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("provider_message_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notification",
        sa.Column("delivery_error_code", sa.String(length=16), nullable=True),
    )
    op.drop_constraint("ck_notification_status", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_status",
        "notification",
        "status IN ('delivered', 'failed', 'skipped', 'queued', 'sent')",
    )


def downgrade() -> None:
    # A 'sent' row is one the gateway accepted and no receipt has settled.
    # Down-grading to a build that cannot express that, 'delivered' is the
    # reading it would have written itself for the very same message.
    op.execute(
        "UPDATE notification SET status = 'delivered' WHERE status = 'sent'"
    )
    op.drop_constraint("ck_notification_status", "notification", type_="check")
    op.create_check_constraint(
        "ck_notification_status",
        "notification",
        "status IN ('delivered', 'failed', 'skipped', 'queued')",
    )
    op.drop_column("notification", "delivery_error_code")
    op.drop_column("notification", "provider_message_id")
