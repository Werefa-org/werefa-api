"""Startup validation for the SMS settings block.

A half-configured gateway is the failure mode worth engineering against:
without these checks it surfaces as notifications quietly falling through
to the logger channel, which looks identical to "nobody enabled SMS".
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from pydantic import ValidationError

from werefa.core.config import Settings

# Fields with no default that every Settings() needs; supplied explicitly so
# these tests don't depend on whatever the developer's .env happens to hold.
_REQUIRED: dict[str, Any] = {
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "postgres",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "not-the-default-password",
    "SECRET_KEY": "x" * 32,
}


def _settings(**overrides: Any) -> Settings:
    return Settings(**{**_REQUIRED, **overrides})  # type: ignore[arg-type]


def test_sms_is_off_by_default() -> None:
    assert _settings().SMS_PROVIDER == "disabled"


@pytest.mark.parametrize(
    ("overrides", "expected_missing"),
    [
        (
            {},
            "TWILIO_ACCOUNT_SID",
        ),
        (
            {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_FROM_NUMBER": "+15005550006"},
            "TWILIO_AUTH_TOKEN",
        ),
        (
            {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok"},
            "TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID",
        ),
    ],
)
def test_twilio_without_full_credentials_fails_at_startup(
    overrides: dict[str, Any], expected_missing: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        _settings(SMS_PROVIDER="twilio", **overrides)

    assert expected_missing in str(exc.value)


@pytest.mark.parametrize(
    "sender",
    [
        {"TWILIO_FROM_NUMBER": "+15005550006"},
        {"TWILIO_MESSAGING_SERVICE_SID": "MG1"},
    ],
)
def test_twilio_accepts_either_sender_kind(sender: dict[str, Any]) -> None:
    config = _settings(
        SMS_PROVIDER="twilio",
        TWILIO_ACCOUNT_SID="AC1",
        TWILIO_AUTH_TOKEN="tok",
        **sender,
    )
    assert config.SMS_PROVIDER == "twilio"


@pytest.mark.parametrize("bad_cap", [0, -1, 10])
def test_a_useless_body_cap_is_rejected_at_startup(bad_cap: int) -> None:
    # A 0/negative cap would silently disable truncation and send the full
    # body, turning a typo'd env var into unbounded multi-segment bills.
    with pytest.raises(ValidationError):
        _settings(SMS_MAX_BODY_CHARS=bad_cap)


@pytest.mark.parametrize("bad_timeout", [0, -1.5])
def test_a_non_positive_timeout_is_rejected_at_startup(bad_timeout: float) -> None:
    with pytest.raises(ValidationError):
        _settings(SMS_TIMEOUT_SECONDS=bad_timeout)


def test_credentials_are_not_required_for_other_providers() -> None:
    # Only the twilio adapter needs twilio credentials.
    assert _settings(SMS_PROVIDER="console").SMS_PROVIDER == "console"


def test_legacy_stub_flag_maps_to_the_console_provider() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = _settings(SMS_DELIVERY_STUB_ENABLED=True)

    assert config.SMS_PROVIDER == "console"
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_a_real_provider_choice_is_not_overridden_by_the_legacy_flag() -> None:
    config = _settings(
        SMS_DELIVERY_STUB_ENABLED=True,
        SMS_PROVIDER="twilio",
        TWILIO_ACCOUNT_SID="AC1",
        TWILIO_AUTH_TOKEN="tok",
        TWILIO_MESSAGING_SERVICE_SID="MG1",
    )
    assert config.SMS_PROVIDER == "twilio"


def test_legacy_flag_still_wins_over_an_explicit_disabled() -> None:
    """Known limitation, pinned so it is a decision rather than a surprise.

    The flag can only be honoured by filling in the default, so it cannot
    tell "left at disabled" apart from "deliberately set to disabled".
    Someone who wants SMS off must drop the deprecated flag rather than
    set `SMS_PROVIDER=disabled` alongside it.
    """
    config = _settings(SMS_DELIVERY_STUB_ENABLED=True, SMS_PROVIDER="disabled")
    assert config.SMS_PROVIDER == "console"
