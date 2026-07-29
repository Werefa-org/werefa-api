"""Tests for notifier preference resolution (FR-07).

These exercise the *channel selection* path of the application service
without touching the database — we hand-craft a tiny ``User`` and a
fake registry, then assert which notifier(s) get called and what the
final ledger row looks like.

**Email is deliberately absent from the ordering tests.** ``dispatch``
treats every kind in ``EMAIL_COPY_KINDS`` specially: email is lifted out
of the preference loop and sent as an out-of-band copy instead, so that
a queue-critical alert lands in-app *and* in the inbox. Since
``EMAIL_COPY_KINDS`` currently covers every member of
``NotificationKind``, that means email is never the channel recorded on
the ledger row — see ``test_email_is_never_the_primary_channel``. The
ordering rules are therefore exercised with websocket / push / logger,
and the email-copy rule gets its own tests below.

Anything touching the copy path pins ``emails_enabled`` explicitly:
``_try_email_copy`` short-circuits when SMTP is unconfigured, so without
that these assertions would pass or fail depending on whatever is in the
developer's ``.env``.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest

from werefa.core.config import settings
from werefa.notifications.application import service as notifications_service
from werefa.notifications.notifier import NotificationPayload
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)


@dataclass
class _FakeNotifier:
    channel: NotificationChannel
    deliverable: bool = True
    raise_on_send: bool = False
    calls: list[NotificationPayload] = field(default_factory=list)

    def send(self, *, user: Any, payload: NotificationPayload) -> bool:
        self.calls.append(payload)
        if self.raise_on_send:
            raise RuntimeError("synthetic failure")
        return self.deliverable


@dataclass
class _FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    is_active: bool = True
    notification_prefs: list[str] | None = None


@dataclass
class _RecordingSession:
    """Minimal stand-in that captures the persisted Notification row."""

    persisted: list[Any] = field(default_factory=list)

    def add(self, obj: Any) -> None:
        self.persisted.append(obj)

    def flush(self) -> None:
        return None

    def refresh(self, _obj: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_registry() -> Generator[None, None, None]:
    yield
    notifications_service.set_registry(None)


@pytest.fixture(autouse=True)
def _copies_delivered_inline(inline_delivery: object) -> None:
    """The email copy is handed to the delivery worker now rather than
    sent inside ``dispatch``.

    This module is about *channel selection*, so the copy assertions
    below want the old "did it reach the notifier?" question answered
    synchronously. ``inline_delivery`` (see ``conftest.py``) runs the
    real handler on the calling thread to get that back; the hand-off is
    tested in ``test_deferred_dispatch.py``.
    """
    return None


@pytest.fixture
def _emails_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "queue@example.com")
    assert settings.emails_enabled is True


@pytest.fixture
def _emails_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert settings.emails_enabled is False


def _set_registry(*notifiers: _FakeNotifier) -> dict[NotificationChannel, _FakeNotifier]:
    registry = {n.channel: n for n in notifiers}
    notifications_service.set_registry(registry)  # type: ignore[arg-type]
    return registry


def _payload(kind: NotificationKind = NotificationKind.head_to_counter) -> NotificationPayload:
    return NotificationPayload(
        kind=kind,
        body="head to counter",
        ticket_id=uuid.uuid4(),
        service_item_id=uuid.uuid4(),
        position=3,
    )


def _dispatch(user: _FakeUser, payload: NotificationPayload | None = None) -> Any:
    row = notifications_service.dispatch(
        session=_RecordingSession(),  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=payload or _payload(),
    )
    assert row is not None
    return row


# --- channel ordering (email excluded — see module docstring) ------------


def test_dispatch_uses_first_deliverable_channel_in_order() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    push = _FakeNotifier(NotificationChannel.push, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, push, log)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "push", "logger"]))

    assert row.channel == NotificationChannel.push.value
    assert row.status == NotificationStatus.delivered.value
    # Logger backstop must NOT be invoked — push already accepted.
    assert log.calls == []
    assert len(ws.calls) == 1
    assert len(push.calls) == 1


def test_dispatch_falls_through_to_logger_when_higher_channels_fail() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    push = _FakeNotifier(NotificationChannel.push, deliverable=False)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, push, log)

    # The user *omitted* logger from prefs, but the service appends it as
    # the always-deliverable backstop so every alert leaves a trail.
    row = _dispatch(_FakeUser(notification_prefs=["websocket", "push"]))

    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value
    assert len(log.calls) == 1


def test_dispatch_records_failure_when_every_channel_declines() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    push = _FakeNotifier(NotificationChannel.push, deliverable=False)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=False)
    _set_registry(ws, push, log)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "push", "logger"]))

    assert row.status == NotificationStatus.failed.value
    # Channel records the *last* tried channel so logs make it obvious
    # that the logger backstop also misbehaved.
    assert row.channel == NotificationChannel.logger.value


def test_dispatch_swallows_notifier_exceptions_and_continues() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, raise_on_send=True)
    push = _FakeNotifier(NotificationChannel.push, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, push, log)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "push", "logger"]))

    assert row.channel == NotificationChannel.push.value
    assert row.status == NotificationStatus.delivered.value


def test_dispatch_skips_unknown_channel_keys() -> None:
    push = _FakeNotifier(NotificationChannel.push, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(push, log)

    # "carrier_pigeon" is not a NotificationChannel member and is dropped
    # during preference resolution.
    row = _dispatch(_FakeUser(notification_prefs=["carrier_pigeon", "push"]))

    assert row.channel == NotificationChannel.push.value
    assert push.calls and not log.calls


def test_dispatch_skips_channels_with_no_registered_notifier() -> None:
    # push is in prefs but absent from the registry: skipped without being
    # recorded as a failed attempt, so the ledger blames logger, not push.
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(log)

    row = _dispatch(_FakeUser(notification_prefs=["push", "logger"]))

    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_dispatch_uses_default_prefs_when_user_has_none() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, log)

    row = _dispatch(_FakeUser(notification_prefs=None))

    # Default prefs are ["websocket", "email", "logger"]; websocket is only
    # reachable via those defaults (the backstop appends logger alone), so
    # winning on websocket proves the defaults were consulted.
    assert row.channel == NotificationChannel.websocket.value
    assert len(ws.calls) == 1


# --- the email-copy rule -------------------------------------------------


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_email_is_never_the_primary_channel(
    kind: NotificationKind, _emails_disabled: None
) -> None:
    """Every kind is in EMAIL_COPY_KINDS, so email never wins the loop.

    Parametrised over the whole enum so that adding a kind *outside*
    ``EMAIL_COPY_KINDS`` fails here — that would be a real behaviour
    change (email becomes a primary channel again) and should not pass
    silently.
    """
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(email, log)

    row = _dispatch(
        _FakeUser(notification_prefs=["email", "logger"]), _payload(kind)
    )

    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value
    # Deferred out of the loop, and the copy is skipped because SMTP is
    # unconfigured — so email is not contacted at all.
    assert email.calls == []


def test_dispatch_sends_email_copy_when_websocket_wins(
    _emails_enabled: None,
) -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=True)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, email, log)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "email", "logger"]))

    # Websocket is what the ledger records...
    assert row.channel == NotificationChannel.websocket.value
    # ...but email still goes out alongside it (in-app + inbox).
    assert len(ws.calls) == 1
    assert len(email.calls) == 1


def test_email_copy_is_skipped_when_smtp_is_unconfigured(
    _emails_disabled: None,
) -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=True)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    _set_registry(ws, email)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "email"]))

    assert row.channel == NotificationChannel.websocket.value
    assert email.calls == []


def test_no_email_copy_when_the_user_has_not_opted_into_email(
    _emails_enabled: None,
) -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=True)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    _set_registry(ws, email)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "logger"]))

    assert row.channel == NotificationChannel.websocket.value
    assert email.calls == []


def test_email_copy_still_sent_when_primary_delivery_fails(
    _emails_enabled: None,
) -> None:
    """The copy is independent of the loop's outcome.

    Even when every preferred channel declines and the ledger row is
    ``failed``, the queue-critical alert still reaches the inbox.
    """
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=False)
    _set_registry(ws, email, log)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "email", "logger"]))

    assert row.status == NotificationStatus.failed.value
    assert len(email.calls) == 1


def test_a_crashing_email_copy_does_not_break_dispatch(
    _emails_enabled: None,
) -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=True)
    email = _FakeNotifier(NotificationChannel.email, raise_on_send=True)
    _set_registry(ws, email)

    row = _dispatch(_FakeUser(notification_prefs=["websocket", "email"]))

    # The ledger row is still written and still reports the real channel.
    assert row.channel == NotificationChannel.websocket.value
    assert row.status == NotificationStatus.delivered.value
