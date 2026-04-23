"""Notifier abstraction for outbound user alerts (FR-07).

The ``Notifier`` protocol intentionally returns a *boolean* "delivered?"
rather than raising on failure. The dispatcher walks a user's preference
list in order and stops on the first ``True`` — that's the channel that
gets recorded as ``delivered`` in the notification ledger; the rest are
recorded as ``skipped`` so the audit trail is complete without spamming
the network.

Tests stub the registry by passing in a fake notifier per channel, which
is why the registry is a plain dict mapping rather than a global module
singleton.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from werefa.shared.enums import NotificationChannel, NotificationKind
from werefa.shared.models import User, utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationPayload:
    """All the data a notifier needs to deliver one alert."""

    kind: NotificationKind
    body: str
    ticket_id: uuid.UUID | None = None
    service_item_id: uuid.UUID | None = None
    position: int | None = None
    occurred_at: datetime | None = None

    def with_default_time(self) -> NotificationPayload:
        if self.occurred_at is not None:
            return self
        return NotificationPayload(
            kind=self.kind,
            body=self.body,
            ticket_id=self.ticket_id,
            service_item_id=self.service_item_id,
            position=self.position,
            occurred_at=utcnow(),
        )


class Notifier(Protocol):
    """One transport (websocket, email, logger, ...).

    Implementations *must* return ``False`` on a "channel cannot deliver
    right now" condition (e.g. SMTP not configured, realtime hub offline)
    so the dispatcher can fall through to the next preference. They
    *should* swallow transient errors and log them rather than raising.
    """

    channel: NotificationChannel

    def send(self, *, user: User, payload: NotificationPayload) -> bool: ...


class LoggerNotifier:
    """Always-deliverable backstop. Writes a structured log line."""

    channel = NotificationChannel.logger

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        logger.info(
            "notification_delivered_via_logger",
            extra={
                "user_id": str(user.id),
                "kind": payload.kind.value,
                "ticket_id": (
                    str(payload.ticket_id) if payload.ticket_id else None
                ),
                "position": payload.position,
                "body": payload.body,
            },
        )
        return True


class WebSocketNotifier:
    """Publishes a ``notify_v1`` event on the ticket's service-line channel.

    The realtime layer is best-effort: if the coordinator isn't running
    yet (process startup) or no event loop is available, we report
    "could not deliver" so the dispatcher falls through to the next
    channel.
    """

    channel = NotificationChannel.websocket

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        # Imported lazily so this module stays importable without the
        # realtime package being initialised (e.g. in pure-rule tests).
        from werefa.realtime import lifespan
        from werefa.realtime.domain.events import NotifyEventV1

        coordinator = lifespan.coordinator
        loop = lifespan.main_event_loop
        if (
            coordinator is None
            or loop is None
            or not loop.is_running()
            or payload.ticket_id is None
            or payload.service_item_id is None
        ):
            return False

        event = NotifyEventV1(
            ticket_id=payload.ticket_id,
            service_item_id=payload.service_item_id,
            kind=payload.kind.value,  # type: ignore[arg-type]
            position=payload.position or 1,
            body=payload.body,
            occurred_at=payload.occurred_at or utcnow(),
        )
        text = event.model_dump_json()
        try:
            loop.create_task(coordinator.publish(payload.service_item_id, text))
        except RuntimeError:
            # ``create_task`` raises if the loop is not running on this
            # thread; treat as a non-delivery so the dispatcher can try
            # the next channel.
            return False
        return True


class EmailNotifier:
    """SMTP delivery for queue alerts (FR-07)."""

    channel = NotificationChannel.email

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        from werefa.core.config import settings
        from werefa.utils import (
            generate_queue_notification_email,
            queue_notification_subject,
            send_email,
            ticket_deep_link,
        )

        if not settings.emails_enabled:
            return False
        if not user.email:
            return False
        ticket_link = (
            ticket_deep_link(str(payload.ticket_id))
            if payload.ticket_id is not None
            else None
        )
        subject = queue_notification_subject(payload.kind.value)
        email_data = generate_queue_notification_email(
            email_to=user.email,
            subject=subject,
            body=payload.body,
            ticket_link=ticket_link,
            position=payload.position,
        )
        try:
            send_email(
                email_to=user.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )
        except Exception:
            logger.exception(
                "notification_email_send_failed",
                extra={"user_id": str(user.id), "kind": payload.kind.value},
            )
            return False
        return True


class PushNotifier:
    """FCM/APNs-style push — integration placeholder (FR-07)."""

    channel = NotificationChannel.push

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        from werefa.core.config import settings

        if not settings.PUSH_DELIVERY_STUB_ENABLED:
            logger.info(
                "notification_push_skipped",
                extra={"user_id": str(user.id)},
            )
            return False
        logger.info(
            "notification_push_stub_delivered",
            extra={"user_id": str(user.id), "kind": payload.kind.value},
        )
        return True


class SmsNotifier:
    """SMS gateway — Twilio-class integration placeholder."""

    channel = NotificationChannel.sms

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        from werefa.core.config import settings

        if not settings.SMS_DELIVERY_STUB_ENABLED:
            logger.info(
                "notification_sms_skipped",
                extra={"user_id": str(user.id)},
            )
            return False
        logger.info(
            "notification_sms_stub_delivered",
            extra={"user_id": str(user.id), "kind": payload.kind.value},
        )
        return True


def default_registry() -> dict[NotificationChannel, Notifier]:
    """Build the shipping registry.

    Held by the application service via a module-level cache so tests
    can swap individual entries without touching globals.
    """
    return {
        NotificationChannel.websocket: WebSocketNotifier(),
        NotificationChannel.email: EmailNotifier(),
        NotificationChannel.push: PushNotifier(),
        NotificationChannel.sms: SmsNotifier(),
        NotificationChannel.logger: LoggerNotifier(),
    }
