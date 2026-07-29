"""Gateway selection — the part that keeps us off a single vendor.

The point of these is that swapping providers is a config change plus one
adapter, and that a bad ``SMS_PROVIDER`` value fails loudly instead of
silently disabling notifications.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from werefa.core.config import settings
from werefa.notifications.infrastructure.sms import factory
from werefa.notifications.infrastructure.sms.base import (
    DisabledSmsProvider,
    SmsMessage,
    SmsOutcome,
    SmsProvider,
    SmsResult,
)
from werefa.notifications.infrastructure.sms.console import ConsoleSmsProvider
from werefa.notifications.infrastructure.sms.twilio import TwilioSmsProvider


@pytest.fixture(autouse=True)
def _restore_registry() -> Generator[None, None, None]:
    original = dict(factory._FACTORIES)
    yield
    factory._FACTORIES.clear()
    factory._FACTORIES.update(original)
    factory.set_sms_provider(None)


class _AcmeSmsProvider:
    """Stands in for a future adapter — an aggregator, an MNO endpoint."""

    name = "acme"

    @property
    def configured(self) -> bool:
        return True

    def send(self, message: SmsMessage) -> SmsResult:
        return SmsResult.sent(provider=self.name, provider_message_id="acme-1")


def test_builtin_providers_are_registered() -> None:
    assert factory.known_sms_providers() == ["console", "disabled", "twilio"]


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("disabled", DisabledSmsProvider),
        ("console", ConsoleSmsProvider),
        ("twilio", TwilioSmsProvider),
    ],
)
def test_each_name_builds_its_adapter(name: str, expected_type: type) -> None:
    assert isinstance(factory.build_sms_provider(name), expected_type)


@pytest.mark.parametrize("name", ["TWILIO", " Twilio ", "twilio"])
def test_provider_names_are_case_and_whitespace_insensitive(name: str) -> None:
    assert isinstance(factory.build_sms_provider(name), TwilioSmsProvider)


def test_a_new_gateway_needs_no_change_to_the_factory_or_settings() -> None:
    factory.register_sms_provider("acme", _AcmeSmsProvider)

    assert "acme" in factory.known_sms_providers()
    provider = factory.build_sms_provider("acme")
    assert isinstance(provider, _AcmeSmsProvider)
    assert provider.send(SmsMessage(to="+251911234567", body="hi")).accepted


def test_unknown_provider_fails_loudly_and_names_the_alternatives() -> None:
    with pytest.raises(ValueError) as exc:
        factory.build_sms_provider("twillio")  # typo

    message = str(exc.value)
    assert "twillio" in message
    assert "twilio" in message
    assert "console" in message


def test_default_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SMS_PROVIDER", "console")
    assert isinstance(factory.build_sms_provider(), ConsoleSmsProvider)


def test_empty_provider_setting_falls_back_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMS_PROVIDER", "")
    assert isinstance(factory.build_sms_provider(), DisabledSmsProvider)


def test_get_sms_provider_caches_and_set_sms_provider_overrides() -> None:
    factory.set_sms_provider(None)
    first = factory.get_sms_provider()
    assert factory.get_sms_provider() is first

    replacement = _AcmeSmsProvider()
    factory.set_sms_provider(replacement)
    assert factory.get_sms_provider() is replacement

    factory.set_sms_provider(None)
    assert factory.get_sms_provider() is not replacement


def test_disabled_provider_reports_unavailable_not_rejected() -> None:
    # "SMS is off" is a deployment state, not a problem with the message —
    # so it must not look like a permanent failure in the logs.
    result = DisabledSmsProvider().send(SmsMessage(to="+251911234567", body="hi"))

    assert result.outcome is SmsOutcome.unavailable
    assert result.retryable is True
    assert result.error_code == "sms_disabled"


def test_console_provider_reports_delivery_for_local_development() -> None:
    provider = ConsoleSmsProvider()
    assert provider.configured is True
    result = provider.send(SmsMessage(to="+251911234567", body="hi"))
    assert result.accepted
    assert result.provider_message_id is not None


@pytest.mark.parametrize(
    "provider",
    [DisabledSmsProvider(), ConsoleSmsProvider(), _AcmeSmsProvider()],
)
def test_adapters_satisfy_the_port(provider: SmsProvider) -> None:
    assert isinstance(provider, SmsProvider)
