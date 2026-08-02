"""The delivery-receipt webhook, end to end against a real ledger row.

This is where the loop closes: the send records that Twilio *took* the
message, and this route records what the carrier did with it. The pure
policy is covered in ``components/notifications/test_receipts.py`` and the
signature algorithm in ``test_sms_receipts.py``; what is asserted here is
the wiring — that a signed callback finds its row, that an unsigned one
cannot, and that the callbacks which legitimately change nothing do not
provoke a retry storm.

Everything runs through the real router, so a route that stops being
mounted, or a query parameter that stops being read, fails here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from werefa.shared.models import Notification

AUTH_TOKEN = "webhook-test-auth-token"
CALLBACK_PATH = "/api/v1/webhooks/twilio/sms-status"
PUBLIC_URL = f"https://testserver{CALLBACK_PATH}"


@pytest.fixture(autouse=True)
def _twilio_callback_configured() -> Generator[None, None, None]:
    """``settings`` is process-global, so put it back afterwards."""
    prev_url = settings.TWILIO_STATUS_CALLBACK_URL
    prev_token = settings.TWILIO_AUTH_TOKEN
    settings.TWILIO_STATUS_CALLBACK_URL = PUBLIC_URL
    settings.TWILIO_AUTH_TOKEN = AUTH_TOKEN
    yield
    settings.TWILIO_STATUS_CALLBACK_URL = prev_url
    settings.TWILIO_AUTH_TOKEN = prev_token


def _row(db: Session, *, status: NotificationStatus, channel: NotificationChannel):
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    row = Notification(
        user_id=su.id,
        kind=NotificationKind.liveness_ping_request.value,
        body="You're near the front — tap to confirm you're on the way.",
        channel=channel.value,
        status=status.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _callback(
    client: TestClient,
    *,
    notification_id: uuid.UUID,
    message_status: str,
    error_code: str | None = None,
    sign: bool = True,
    token: str = AUTH_TOKEN,
):
    params = {
        "MessageSid": "SM11111111111111111111111111111111",
        "MessageStatus": message_status,
        "AccountSid": "AC00000000000000000000000000000000",
        "To": "+251911234567",
    }
    if error_code is not None:
        params["ErrorCode"] = error_code

    url = f"{CALLBACK_PATH}?nid={notification_id}"
    headers = {}
    if sign:
        payload = PUBLIC_URL + f"?nid={notification_id}"
        payload += "".join(f"{k}{params[k]}" for k in sorted(params))
        headers["X-Twilio-Signature"] = base64.b64encode(
            hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
        ).decode()
    return client.post(url, data=params, headers=headers)


def test_a_delivered_receipt_confirms_the_alert_reached_them(
    client: TestClient, db: Session
) -> None:
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )

    r = _callback(client, notification_id=row.id, message_status="delivered")
    assert r.status_code == 204, r.text

    db.refresh(row)
    assert row.status == NotificationStatus.delivered.value
    assert row.provider_message_id == "SM11111111111111111111111111111111"
    assert row.delivery_error_code is None


def test_an_undelivered_receipt_records_that_nobody_was_told(
    client: TestClient, db: Session
) -> None:
    """The case the ledger could not express before.

    Twilio accepted this message and the carrier then dropped it — 30003
    is a handset that is unreachable. Recorded honestly, FR-05 liveness
    stops counting the customer's silence against them.
    """
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )

    r = _callback(
        client,
        notification_id=row.id,
        message_status="undelivered",
        error_code="30003",
    )
    assert r.status_code == 204, r.text

    db.refresh(row)
    assert row.status == NotificationStatus.failed.value
    assert row.delivery_error_code == "30003"


def test_an_intermediate_callback_leaves_the_row_alone(
    client: TestClient, db: Session
) -> None:
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )

    r = _callback(client, notification_id=row.id, message_status="sending")
    # 204 rather than an error: Twilio retries anything else, and we
    # understood this one perfectly well and chose to ignore it.
    assert r.status_code == 204, r.text

    db.refresh(row)
    assert row.status == NotificationStatus.sent.value


def test_an_unsigned_callback_cannot_touch_the_ledger(
    client: TestClient, db: Session
) -> None:
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )

    r = _callback(
        client, notification_id=row.id, message_status="delivered", sign=False
    )
    assert r.status_code == 403

    db.refresh(row)
    assert row.status == NotificationStatus.sent.value


def test_a_forged_signature_cannot_mark_an_alert_delivered(
    client: TestClient, db: Session
) -> None:
    """Not a theoretical concern.

    The liveness flow now treats "this alert reached them" as evidence
    that a silent customer chose not to answer, so a forgeable receipt is
    a way to get somebody flagged.
    """
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )

    r = _callback(
        client,
        notification_id=row.id,
        message_status="delivered",
        token="not-the-account-token",
    )
    assert r.status_code == 403

    db.refresh(row)
    assert row.status == NotificationStatus.sent.value


def test_a_receipt_for_a_row_that_fell_through_is_ignored(
    client: TestClient, db: Session
) -> None:
    """SMS failed, the alert went out on another channel, then the carrier
    finally reported back. That row is no longer SMS's to settle."""
    row = _row(
        db,
        status=NotificationStatus.delivered,
        channel=NotificationChannel.logger,
    )

    r = _callback(client, notification_id=row.id, message_status="undelivered")
    assert r.status_code == 204, r.text

    db.refresh(row)
    assert row.status == NotificationStatus.delivered.value
    assert row.channel == NotificationChannel.logger.value


def test_a_callback_for_an_unknown_row_is_not_an_error(
    client: TestClient,
) -> None:
    # The ticket cascade removed it, most likely. Answering anything but
    # success just buys a replay of a callback with nowhere to go.
    r = _callback(
        client, notification_id=uuid.uuid4(), message_status="delivered"
    )
    assert r.status_code == 204, r.text


def test_the_endpoint_is_closed_when_no_callback_url_is_published(
    client: TestClient, db: Session
) -> None:
    """Nothing was asked to call us, so anything arriving is unsolicited."""
    row = _row(
        db, status=NotificationStatus.sent, channel=NotificationChannel.sms
    )
    settings.TWILIO_STATUS_CALLBACK_URL = None

    r = _callback(client, notification_id=row.id, message_status="delivered")
    assert r.status_code == 404

    db.refresh(row)
    assert row.status == NotificationStatus.sent.value
