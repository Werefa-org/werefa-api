"""Twilio adapter: request shape and how each response maps onto an outcome.

Driven through ``httpx.MockTransport``, so the real request-building and
response-parsing code runs — only the socket is faked. The response bodies
are copied from Twilio's documented payloads.
"""

from __future__ import annotations

import httpx
import pytest

from werefa.notifications.infrastructure.sms.base import SmsMessage, SmsOutcome
from werefa.notifications.infrastructure.sms.twilio import TwilioSmsProvider

ACCOUNT_SID = "AC00000000000000000000000000000000"
AUTH_TOKEN = "test-auth-token"
MESSAGE = SmsMessage(to="+251911234567", body="Werefa: You're next in line.")


def _provider(
    handler: object, **overrides: object
) -> tuple[TwilioSmsProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator]

    kwargs: dict[str, object] = {
        "account_sid": ACCOUNT_SID,
        "auth_token": AUTH_TOKEN,
        "from_number": "+15005550006",
    }
    kwargs.update(overrides)
    provider = TwilioSmsProvider(
        client=httpx.Client(transport=httpx.MockTransport(_record)),
        **kwargs,  # type: ignore[arg-type]
    )
    return provider, seen


def _json(status_code: int, payload: dict[str, object]):
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return _handler


def _accepted() -> dict[str, object]:
    return {
        "sid": "SM11111111111111111111111111111111",
        "status": "queued",
        "error_code": None,
        "error_message": None,
        "to": MESSAGE.to,
    }


# --- request shape -------------------------------------------------------


def test_request_targets_the_messages_resource_with_basic_auth() -> None:
    provider, seen = _provider(_json(201, _accepted()))
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.sent
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == (
        f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"
    )
    assert request.headers["authorization"].startswith("Basic ")
    body = dict(httpx.QueryParams(request.content.decode()))
    assert body == {
        "To": MESSAGE.to,
        "Body": MESSAGE.body,
        "From": "+15005550006",
    }


def test_messaging_service_replaces_the_from_number_when_both_are_set() -> None:
    provider, seen = _provider(
        _json(201, _accepted()),
        messaging_service_sid="MG00000000000000000000000000000000",
    )
    provider.send(MESSAGE)

    body = dict(httpx.QueryParams(seen[0].content.decode()))
    assert body["MessagingServiceSid"] == "MG00000000000000000000000000000000"
    assert "From" not in body


def test_base_url_is_overridable_for_staging_fakes() -> None:
    provider, seen = _provider(
        _json(201, _accepted()), base_url="http://localhost:4010/"
    )
    provider.send(MESSAGE)
    assert str(seen[0].url).startswith("http://localhost:4010/2010-04-01/")


def test_auth_token_never_appears_in_the_request_body() -> None:
    provider, seen = _provider(_json(201, _accepted()))
    provider.send(MESSAGE)
    assert AUTH_TOKEN not in seen[0].content.decode()


# --- outcome mapping -----------------------------------------------------


def test_accepted_message_returns_the_provider_message_id() -> None:
    provider, _ = _provider(_json(201, _accepted()))
    result = provider.send(MESSAGE)

    assert result.accepted is True
    assert result.provider == "twilio"
    assert result.provider_message_id == "SM11111111111111111111111111111111"


def test_two_hundred_with_failed_status_is_a_rejection() -> None:
    provider, _ = _provider(
        _json(
            201,
            {
                "sid": "SM2",
                "status": "failed",
                "error_code": 21610,
                "error_message": "Attempt to send to unsubscribed recipient",
            },
        )
    )
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.rejected
    assert result.retryable is False
    assert result.error_code == "21610"


def test_invalid_number_is_permanent() -> None:
    provider, _ = _provider(
        _json(
            400,
            {
                "code": 21211,
                "message": "The 'To' number is not a valid phone number.",
                "status": 400,
            },
        )
    )
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.rejected
    assert result.retryable is False
    assert result.error_code == "21211"
    assert "not a valid phone number" in (result.error_detail or "")


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_gateway_server_errors_are_retryable(status_code: int) -> None:
    provider, _ = _provider(_json(status_code, {"message": "upstream boom"}))
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert result.retryable is True


def test_rate_limiting_is_retryable() -> None:
    provider, _ = _provider(
        _json(429, {"code": 20429, "message": "Too Many Requests", "status": 429})
    )
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert result.error_code == "20429"


def test_transient_twilio_code_on_a_4xx_is_still_retryable() -> None:
    # 31206 arrives as a plain 400 but means "slow down", not "bad message".
    provider, _ = _provider(
        _json(400, {"code": 31206, "message": "Rate exceeded", "status": 400})
    )
    assert provider.send(MESSAGE).outcome is SmsOutcome.unavailable


@pytest.mark.parametrize("status_code", [401, 403])
def test_bad_credentials_are_reported_as_unavailable_not_rejected(
    status_code: int,
) -> None:
    """Our credentials are broken; the message itself is fine.

    Calling this a rejection would blame the recipient's number in the
    logs and hide an ops problem behind normal channel fall-through.
    """
    provider, _ = _provider(
        _json(status_code, {"code": 20003, "message": "Authenticate", "status": 401})
    )
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert result.retryable is True


def test_timeout_is_retryable_and_does_not_raise() -> None:
    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider, _ = _provider(_timeout)
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert result.error_code == "timeout"


def test_connection_failure_is_retryable_and_does_not_raise() -> None:
    def _refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider, _ = _provider(_refused)
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert result.error_code == "transport_error"


def test_non_json_error_body_still_produces_a_result() -> None:
    def _html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    provider, _ = _provider(_html)
    result = provider.send(MESSAGE)

    assert result.outcome is SmsOutcome.unavailable
    assert "Bad Gateway" in (result.error_detail or "")


# --- configuration -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_sid": None},
        {"auth_token": None},
        {"from_number": None},  # and no messaging service
    ],
)
def test_incomplete_credentials_report_unconfigured(
    overrides: dict[str, object],
) -> None:
    provider, seen = _provider(_json(201, _accepted()), **overrides)

    assert provider.configured is False
    result = provider.send(MESSAGE)
    assert result.outcome is SmsOutcome.unavailable
    assert result.error_code == "twilio_not_configured"
    # No network call is attempted.
    assert seen == []


def test_messaging_service_alone_is_sufficient_configuration() -> None:
    provider, _ = _provider(
        _json(201, _accepted()),
        from_number=None,
        messaging_service_sid="MG00000000000000000000000000000000",
    )
    assert provider.configured is True
