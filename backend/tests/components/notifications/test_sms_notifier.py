"""``SmsNotifier``: when it refuses to send, and how it reports outcomes.

The notifier is the seam between the dispatcher's boolean world and the
gateway's three-outcome world. What matters is that it never sends on
incomplete data, never raises into a queue mutation, and only claims
delivery when the gateway actually accepted the message.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest

from werefa.core.config import settings
from werefa.notifications.infrastructure.sms.base import (
    SmsMessage,
    SmsResult,
)
from werefa.notifications.notifier import NotificationPayload, SmsNotifier
from werefa.shared.enums import NotificationChannel, NotificationKind


@dataclass
class _FakeProvider:
    name: str = "fake"
    configured_value: bool = True
    result: SmsResult | None = None
    raises: bool = False
    sent: list[SmsMessage] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return self.configured_value

    def send(self, message: SmsMessage) -> SmsResult:
        self.sent.append(message)
        if self.raises:
            raise RuntimeError("vendor client exploded")
        return self.result or SmsResult.sent(
            provider=self.name, provider_message_id="fake-1"
        )


@dataclass
class _FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    phone_number: str | None = "+251911234567"
    is_active: bool = True
    notification_prefs: list[str] | None = None


def _payload(**overrides: object) -> NotificationPayload:
    base: dict[str, object] = {
        "kind": NotificationKind.you_are_next,
        "body": "You're next — please head to the counter now.",
        "ticket_id": uuid.uuid4(),
        "service_item_id": uuid.uuid4(),
        "position": 1,
    }
    base.update(overrides)
    return NotificationPayload(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _sms_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SMS_DEFAULT_COUNTRY_CODE", "+251")
    monkeypatch.setattr(settings, "SMS_INCLUDE_TICKET_LINK", True)
    monkeypatch.setattr(settings, "SMS_MAX_BODY_CHARS", 320)


def test_channel_is_sms() -> None:
    assert SmsNotifier().channel is NotificationChannel.sms


def test_delivers_and_reports_true_when_the_gateway_accepts() -> None:
    provider = _FakeProvider()
    assert SmsNotifier(provider).send(user=_FakeUser(), payload=_payload()) is True
    assert len(provider.sent) == 1


def test_message_is_rendered_gsm_safe_branded_and_linked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BRAND_NAME", "Werefa")
    provider = _FakeProvider()
    payload = _payload()

    SmsNotifier(provider).send(user=_FakeUser(), payload=payload)

    body = provider.sent[0].body
    assert body.startswith("Werefa: ")
    assert "—" not in body  # transliterated for GSM-7
    assert str(payload.ticket_id) in body


def test_recipient_is_normalised_to_e164() -> None:
    provider = _FakeProvider()
    SmsNotifier(provider).send(
        user=_FakeUser(phone_number="0911 234 567"), payload=_payload()
    )
    assert provider.sent[0].to == "+251911234567"


def test_ticket_link_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMS_INCLUDE_TICKET_LINK", False)
    provider = _FakeProvider()
    payload = _payload()

    SmsNotifier(provider).send(user=_FakeUser(), payload=payload)
    assert str(payload.ticket_id) not in provider.sent[0].body


def test_idempotency_key_is_stable_per_ticket_and_kind() -> None:
    provider = _FakeProvider()
    payload = _payload()
    notifier = SmsNotifier(provider)

    notifier.send(user=_FakeUser(), payload=payload)
    notifier.send(user=_FakeUser(), payload=payload)

    keys = {m.idempotency_key for m in provider.sent}
    assert keys == {f"{payload.ticket_id}:{payload.kind.value}"}


def test_no_key_when_the_alert_is_not_tied_to_a_ticket() -> None:
    provider = _FakeProvider()
    SmsNotifier(provider).send(
        user=_FakeUser(),
        payload=_payload(ticket_id=None, kind=NotificationKind.queue_cleared),
    )
    assert provider.sent[0].idempotency_key is None


# --- refusals ------------------------------------------------------------


def test_unconfigured_gateway_skips_without_sending() -> None:
    provider = _FakeProvider(configured_value=False)
    assert SmsNotifier(provider).send(user=_FakeUser(), payload=_payload()) is False
    assert provider.sent == []


@pytest.mark.parametrize("phone", [None, "", "not a phone", "12"])
def test_unusable_phone_number_skips_without_sending(phone: str | None) -> None:
    provider = _FakeProvider()
    assert (
        SmsNotifier(provider).send(
            user=_FakeUser(phone_number=phone), payload=_payload()
        )
        is False
    )
    assert provider.sent == []


def test_national_number_is_skipped_when_no_default_country_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMS_DEFAULT_COUNTRY_CODE", None)
    provider = _FakeProvider()
    assert (
        SmsNotifier(provider).send(
            user=_FakeUser(phone_number="0911234567"), payload=_payload()
        )
        is False
    )
    assert provider.sent == []


@pytest.mark.parametrize(
    "result",
    [
        SmsResult.rejected(provider="fake", error_code="21211"),
        SmsResult.unavailable(provider="fake", error_code="timeout"),
    ],
)
def test_non_accepted_outcomes_report_undelivered(result: SmsResult) -> None:
    provider = _FakeProvider(result=result)
    assert SmsNotifier(provider).send(user=_FakeUser(), payload=_payload()) is False


def test_a_crashing_gateway_never_escapes_the_notifier() -> None:
    # A text message must not be able to fail a queue mutation.
    provider = _FakeProvider(raises=True)
    assert SmsNotifier(provider).send(user=_FakeUser(), payload=_payload()) is False


def test_provider_is_resolved_lazily_when_none_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from werefa.notifications.infrastructure.sms import factory

    provider = _FakeProvider()
    monkeypatch.setattr(factory, "_provider", provider)

    # No provider passed to the constructor — it must come from the
    # module-level cache, so ``set_sms_provider`` works without rebuilding
    # the notifier registry.
    assert SmsNotifier().send(user=_FakeUser(), payload=_payload()) is True
    assert len(provider.sent) == 1


# --- wiring through the real dispatcher ----------------------------------


@dataclass
class _RecordingSession:
    """Captures the ledger row without touching the database."""

    persisted: list[object] = field(default_factory=list)

    def add(self, obj: object) -> None:
        self.persisted.append(obj)

    def flush(self) -> None:
        return None

    def refresh(self, _obj: object) -> None:
        return None


@pytest.fixture
def _real_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[_FakeProvider, None, None]:
    """Ship registry + shipping SmsNotifier, with only the gateway faked."""
    from werefa.notifications.application import service as notifications_service
    from werefa.notifications.infrastructure.sms import factory

    provider = _FakeProvider()
    monkeypatch.setattr(factory, "_provider", provider)
    notifications_service.set_registry(None)
    monkeypatch.setattr(settings, "BRAND_NAME", "Werefa")
    yield provider
    notifications_service.set_registry(None)


def test_sms_preference_reaches_the_gateway_and_lands_in_the_ledger(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """End-to-end through ``default_registry()``.

    Guards the wiring the unit tests above deliberately bypass: channel
    enum → registry entry → notifier → gateway → recorded ledger row.

    The gateway is reached from the *delivery worker* now, not from
    ``dispatch`` — ``inline_delivery`` runs that worker on this thread so
    the end-to-end assertion stays one call long. That the send is
    deferred at all is asserted in ``test_deferred_dispatch.py``.
    """
    from werefa.notifications.application import service as notifications_service
    from werefa.shared.enums import NotificationStatus

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value
    assert len(_real_registry.sent) == 1
    assert _real_registry.sent[0].to == "+251911234567"
    assert _real_registry.sent[0].body.startswith("Werefa: ")


def test_dispatch_falls_through_when_the_gateway_declines(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """Fall-through survived the move onto the worker.

    ``unavailable`` is retryable, so the worker exhausts its budget on
    SMS first and only then takes the next preference — the alert still
    ends up on the logger backstop and is never silently lost.
    """
    from werefa.notifications.application import service as notifications_service
    from werefa.shared.enums import NotificationStatus

    _real_registry.result = SmsResult.unavailable(
        provider="fake", error_code="timeout"
    )

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert len(_real_registry.sent) > 1, "a transient decline should be retried"
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_rejected_number_is_not_retried_before_falling_through(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """The other half of the retry split: ``rejected`` is permanent, so
    the worker moves straight on instead of re-sending to a bad number."""
    from werefa.notifications.application import service as notifications_service

    _real_registry.result = SmsResult.rejected(
        provider="fake", error_code="21211"
    )

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert len(_real_registry.sent) == 1
    assert row.channel == NotificationChannel.logger.value


def test_users_without_sms_in_prefs_are_never_texted(
    _real_registry: _FakeProvider,
) -> None:
    from werefa.notifications.application import service as notifications_service

    session = _RecordingSession()
    notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=_FakeUser(notification_prefs=["logger"]),  # type: ignore[call-arg]
        payload=_payload(),
    )

    assert _real_registry.sent == []


# --- acceptance is not arrival ---------------------------------------------


def test_a_gateway_that_owes_a_receipt_leaves_the_row_unsettled(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """The whole point of the receipt work, at the ledger level.

    Twilio returning a 201 means it queued the message; the carrier's
    verdict arrives later on the status callback. Recording that as
    ``delivered`` made a text to a disconnected number and one somebody
    acted on the same row — and FR-05 liveness then read our optimism
    back as proof the customer had been warned.
    """
    from werefa.notifications.application import service as notifications_service
    from werefa.shared.enums import NotificationStatus

    _real_registry.result = SmsResult.sent(
        provider="fake", provider_message_id="SM1", receipt_expected=True
    )

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.sent.value


def test_awaiting_a_receipt_does_not_send_the_alert_twice(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """``accepted`` ends the preference walk exactly like ``delivered``.

    The message is with the carrier; falling through to the logger — or
    worse, to another remote channel — because no receipt has arrived yet
    would double-notify everyone whose gateway is simply not instant.
    """
    from werefa.notifications.application import service as notifications_service

    _real_registry.result = SmsResult.sent(
        provider="fake", receipt_expected=True
    )

    notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert len(_real_registry.sent) == 1


def test_a_gateway_with_no_receipts_still_settles_the_row_immediately(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """``TWILIO_STATUS_CALLBACK_URL`` unset is the rollback lever.

    Without it nothing will ever call back, so parking the row at 'sent'
    would strand it forever — a worse lie than the optimism it replaced.
    """
    from werefa.notifications.application import service as notifications_service
    from werefa.shared.enums import NotificationStatus

    _real_registry.result = SmsResult.sent(provider="fake")

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert row.status == NotificationStatus.delivered.value


def test_the_gateway_is_told_which_ledger_row_to_report_against(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """Only the worker knows the row id, so only the worker can supply it.

    ``dispatch`` writes the ledger row *after* it picks the channel, so a
    payload built on the request thread has nothing to quote — the worker
    stamps it on before handing the send to the notifier.
    """
    from werefa.notifications.application import service as notifications_service

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert row is not None
    assert _real_registry.sent[0].receipt_reference == str(row.id)


def test_a_closed_app_gets_a_text_instead_of_a_silent_success(
    _real_registry: _FakeProvider, inline_delivery: Any
) -> None:
    """The fall-through that was missing, end to end.

    With the shipped preferences (``websocket`` first) a customer whose
    app is closed produced a publish to zero subscribers, which reported
    itself delivered. Dispatch stopped there: the ledger said the alert
    went out, SMS was never attempted, and nothing arrived anywhere.

    Nobody is subscribed here — there is no realtime coordinator running
    at all — so the websocket channel must decline and let the gateway
    have it.
    """
    from werefa.notifications.application import service as notifications_service
    from werefa.shared.enums import NotificationStatus

    row = notifications_service.dispatch(
        session=inline_delivery.session(),  # type: ignore[arg-type]
        user=inline_delivery.recipient(
            _FakeUser(notification_prefs=["websocket", "sms", "logger"])  # type: ignore[call-arg]
        ),
        payload=_payload(),
    )

    assert len(_real_registry.sent) == 1, "the customer was never texted"
    assert row is not None
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value
