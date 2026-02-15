"""Tests for notifier preference resolution (FR-07).

These exercise the *channel selection* path of the application service
without touching the database — we hand-craft a tiny ``User`` and a
fake registry, then assert which notifier(s) get called and what the
final ledger row looks like.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

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
def _reset_registry() -> None:
    yield
    notifications_service.set_registry(None)


def _set_registry(*notifiers: _FakeNotifier) -> dict[NotificationChannel, _FakeNotifier]:
    registry = {n.channel: n for n in notifiers}
    notifications_service.set_registry(registry)  # type: ignore[arg-type]
    return registry


def _payload() -> NotificationPayload:
    return NotificationPayload(
        kind=NotificationKind.head_to_counter,
        body="head to counter",
        ticket_id=uuid.uuid4(),
        service_item_id=uuid.uuid4(),
        position=3,
    )


def test_dispatch_uses_first_deliverable_channel_in_order() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, email, log)

    user = _FakeUser(notification_prefs=["websocket", "email", "logger"])
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    assert row.channel == NotificationChannel.email.value
    assert row.status == NotificationStatus.delivered.value
    # Logger backstop must NOT be invoked — email already accepted.
    assert log.calls == []
    assert len(ws.calls) == 1
    assert len(email.calls) == 1


def test_dispatch_falls_through_to_logger_when_higher_channels_fail() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    email = _FakeNotifier(NotificationChannel.email, deliverable=False)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, email, log)

    user = _FakeUser(notification_prefs=["websocket", "email"])
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    # The user *omitted* logger from prefs, but the service appends it as
    # the always-deliverable backstop so every alert leaves a trail.
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value
    assert len(log.calls) == 1


def test_dispatch_records_failure_when_every_channel_declines() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, deliverable=False)
    email = _FakeNotifier(NotificationChannel.email, deliverable=False)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=False)
    _set_registry(ws, email, log)

    user = _FakeUser(notification_prefs=["websocket", "email", "logger"])
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    assert row.status == NotificationStatus.failed.value
    # Channel records the *last* tried channel so logs make it obvious
    # that the logger backstop also misbehaved.
    assert row.channel == NotificationChannel.logger.value


def test_dispatch_swallows_notifier_exceptions_and_continues() -> None:
    ws = _FakeNotifier(NotificationChannel.websocket, raise_on_send=True)
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(ws, email, log)

    user = _FakeUser(notification_prefs=["websocket", "email", "logger"])
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    assert row.channel == NotificationChannel.email.value
    assert row.status == NotificationStatus.delivered.value


def test_dispatch_skips_unknown_channel_keys() -> None:
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(email, log)

    user = _FakeUser(notification_prefs=["sms", "email"])  # "sms" is unknown
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    assert row.channel == NotificationChannel.email.value
    assert email.calls and not log.calls


def test_dispatch_uses_default_prefs_when_user_has_none() -> None:
    email = _FakeNotifier(NotificationChannel.email, deliverable=True)
    log = _FakeNotifier(NotificationChannel.logger, deliverable=True)
    _set_registry(email, log)

    user = _FakeUser(notification_prefs=None)
    session = _RecordingSession()
    row = notifications_service.dispatch(
        session=session,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        payload=_payload(),
    )
    assert row is not None
    # Default prefs are ["websocket", "email", "logger"]; with WS not
    # registered we should fall through to email.
    assert row.channel == NotificationChannel.email.value
