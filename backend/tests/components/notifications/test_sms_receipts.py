"""Twilio's half of the delivery-receipt conversation.

Three things live in the adapter because they are pure vendor knowledge,
and all three are tested here rather than through the webhook route: how
the send asks for a receipt, how Twilio's ``MessageStatus`` vocabulary
maps onto the ledger's, and how a callback proves it came from Twilio.

The signature test matters more than its size suggests. The callback URL
is unauthenticated by nature — anyone who learns it can POST to it — and
since the liveness flow now trusts "this alert reached the customer" when
deciding whether their silence counts against them, a forgeable receipt
is a way to get somebody flagged, or to stop somebody being flagged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import httpx
import pytest

from werefa.notifications.domain.receipts import ReceiptOutcome
from werefa.notifications.infrastructure.sms.base import SmsMessage
from werefa.notifications.infrastructure.sms.twilio import (
    TwilioSmsProvider,
    classify_status,
    validate_signature,
)

ACCOUNT_SID = "AC00000000000000000000000000000000"
AUTH_TOKEN = "test-auth-token"
CALLBACK = "https://api.example.com/api/v1/webhooks/twilio/sms-status"
ROW_ID = "8f14e45f-ea8c-4f9e-b4d9-1c0f3a5b7d21"

MESSAGE = SmsMessage(
    to="+251911234567",
    body="Werefa: You're next in line.",
    receipt_reference=ROW_ID,
)


def _provider(**overrides: object) -> tuple[TwilioSmsProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201,
            json={
                "sid": "SM11111111111111111111111111111111",
                "status": "queued",
                "error_code": None,
                "error_message": None,
            },
        )

    kwargs: dict[str, object] = {
        "account_sid": ACCOUNT_SID,
        "auth_token": AUTH_TOKEN,
        "from_number": "+15005550006",
        "status_callback_url": CALLBACK,
    }
    kwargs.update(overrides)
    provider = TwilioSmsProvider(
        client=httpx.Client(transport=httpx.MockTransport(_record)),
        **kwargs,  # type: ignore[arg-type]
    )
    return provider, seen


def _body(request: httpx.Request) -> dict[str, str]:
    return dict(httpx.QueryParams(request.content.decode()))


# --- asking for a receipt ------------------------------------------------


def test_the_send_asks_twilio_to_report_back_and_says_which_row() -> None:
    provider, seen = _provider()
    result = provider.send(MESSAGE)

    callback = _body(seen[0])["StatusCallback"]
    assert callback == f"{CALLBACK}?nid={ROW_ID}"
    # The row id travels in the URL rather than being looked up by
    # message SID afterwards: the first callback can arrive before the
    # worker has committed the SID it would be looked up by.
    assert result.receipt_expected is True


def test_a_configured_callback_preserves_query_parameters_already_there() -> None:
    provider, seen = _provider(status_callback_url=f"{CALLBACK}?env=staging")
    provider.send(MESSAGE)

    assert _body(seen[0])["StatusCallback"] == f"{CALLBACK}?env=staging&nid={ROW_ID}"


def test_without_a_configured_url_nothing_is_asked_for() -> None:
    # And the result must say so, or the ledger would park the row at
    # 'sent' waiting for a callback that is never coming.
    provider, seen = _provider(status_callback_url=None)
    result = provider.send(MESSAGE)

    assert "StatusCallback" not in _body(seen[0])
    assert result.accepted is True
    assert result.receipt_expected is False


def test_a_send_that_owns_no_ledger_row_asks_for_no_receipt() -> None:
    # The email-copy case: there is no row for a receipt to update.
    provider, seen = _provider()
    result = provider.send(SmsMessage(to=MESSAGE.to, body=MESSAGE.body))

    assert "StatusCallback" not in _body(seen[0])
    assert result.receipt_expected is False


# --- reading a callback --------------------------------------------------


@pytest.mark.parametrize("status", ["delivered", "read"])
def test_terminal_success_statuses_are_a_delivery(status: str) -> None:
    assert classify_status(status) is ReceiptOutcome.delivered


@pytest.mark.parametrize("status", ["undelivered", "failed", "canceled"])
def test_terminal_failure_statuses_are_a_failure(status: str) -> None:
    assert classify_status(status) is ReceiptOutcome.failed


@pytest.mark.parametrize("status", ["queued", "sending", "sent", "accepted"])
def test_twilios_word_sent_is_not_a_delivery(status: str) -> None:
    # 'sent' at Twilio means "handed to the carrier" — exactly the
    # optimism that made a 201 look like an arrival. Mapping it to
    # delivered here would reintroduce the bug one layer out.
    assert classify_status(status) is ReceiptOutcome.in_flight


@pytest.mark.parametrize("status", [None, "", "something_new"])
def test_an_unrecognised_status_leaves_the_row_alone(status: str | None) -> None:
    # Guessing 'failed' would mark a customer unreachable on a word we do
    # not know; guessing 'delivered' would do the reverse.
    assert classify_status(status) is ReceiptOutcome.in_flight


# --- proving it came from Twilio -----------------------------------------


def _sign(url: str, params: dict[str, str], token: str = AUTH_TOKEN) -> str:
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


CALLBACK_URL = f"{CALLBACK}?nid={ROW_ID}"
PARAMS = {
    "MessageSid": "SM11111111111111111111111111111111",
    "MessageStatus": "delivered",
    "AccountSid": ACCOUNT_SID,
    "To": "+251911234567",
}


def test_a_correctly_signed_callback_is_accepted() -> None:
    assert (
        validate_signature(
            url=CALLBACK_URL,
            params=PARAMS,
            signature=_sign(CALLBACK_URL, PARAMS),
            auth_token=AUTH_TOKEN,
        )
        is True
    )


def test_a_tampered_parameter_invalidates_the_signature() -> None:
    signature = _sign(CALLBACK_URL, PARAMS)
    forged = {**PARAMS, "MessageStatus": "undelivered"}

    assert (
        validate_signature(
            url=CALLBACK_URL,
            params=forged,
            signature=signature,
            auth_token=AUTH_TOKEN,
        )
        is False
    )


def test_pointing_at_another_row_invalidates_the_signature() -> None:
    # The URL is part of what is signed, so a valid receipt cannot be
    # replayed against a different customer's alert.
    other = f"{CALLBACK}?nid=00000000-0000-4000-8000-000000000000"

    assert (
        validate_signature(
            url=other,
            params=PARAMS,
            signature=_sign(CALLBACK_URL, PARAMS),
            auth_token=AUTH_TOKEN,
        )
        is False
    )


def test_a_signature_from_a_different_account_is_rejected() -> None:
    assert (
        validate_signature(
            url=CALLBACK_URL,
            params=PARAMS,
            signature=_sign(CALLBACK_URL, PARAMS, token="someone-elses-token"),
            auth_token=AUTH_TOKEN,
        )
        is False
    )


@pytest.mark.parametrize("signature", [None, ""])
def test_an_unsigned_callback_is_rejected(signature: str | None) -> None:
    assert (
        validate_signature(
            url=CALLBACK_URL,
            params=PARAMS,
            signature=signature,
            auth_token=AUTH_TOKEN,
        )
        is False
    )


def test_no_auth_token_means_we_cannot_verify_and_must_not_pretend() -> None:
    # "We could not check" must never resolve the same way as "checked".
    assert (
        validate_signature(
            url=CALLBACK_URL,
            params=PARAMS,
            signature=_sign(CALLBACK_URL, PARAMS),
            auth_token=None,
        )
        is False
    )
