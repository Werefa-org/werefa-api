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

Channels whose delivery leaves this machine (SMS, email) are not sent on
the request thread any more — the dispatcher hands them to the delivery
worker, which needs two things a bare ``bool`` cannot express: whether a
failure is worth retrying, and whether the channel is configured at all.
Both live on *optional* companion members (:class:`RetryAwareNotifier`)
rather than on ``Notifier`` itself, so every existing notifier — and
every fake in the test suite — keeps working untouched.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from werefa.shared.enums import NotificationChannel, NotificationKind
from werefa.shared.models import User, utcnow

if TYPE_CHECKING:
    # Import-time only: keeps this module loadable in pure-rule tests that
    # never touch the SMS stack, matching how the realtime import is
    # deferred inside ``WebSocketNotifier.send``.
    from werefa.notifications.infrastructure.sms import SmsProvider

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


class DeliveryOutcome(str, Enum):
    """What the delivery worker should do next about one send.

    Coarser than any gateway's error catalogue and finer than the ``bool``
    the dispatcher wants, because "retry, or move to the next channel?"
    is the only extra distinction the worker has to make.
    """

    delivered = "delivered"
    transient = "transient"
    """Worth trying again — timeout, 5xx, rate limit, SMTP hiccup."""

    permanent = "permanent"
    """Never going to work — bad number, no address, channel switched off."""


class RetryAwareNotifier(Protocol):
    """A :class:`Notifier` that also answers the retry question.

    Implemented by the channels the delivery worker actually queues (SMS
    and email). ``ready`` is what lets the dispatcher keep its fast path:
    a channel that reports ``False`` is skipped inline exactly as it is
    today, so a deployment with ``SMS_PROVIDER=disabled`` never writes a
    ``queued`` ledger row it would only have to walk back a moment later.

    Both members deliberately keep vendor knowledge inside the notifier —
    the dispatcher must never learn what "configured" means for a
    particular gateway.
    """

    channel: NotificationChannel

    @property
    def ready(self) -> bool: ...

    def send(self, *, user: User, payload: NotificationPayload) -> bool: ...

    def deliver(
        self, *, user: User, payload: NotificationPayload
    ) -> DeliveryOutcome: ...


def channel_is_ready(notifier: Notifier) -> bool:
    """Can this channel deliver at all right now?

    Notifiers that don't advertise ``ready`` are the in-process ones
    (websocket, push, logger); they are always worth trying because
    trying costs nothing.
    """
    ready = getattr(notifier, "ready", None)
    return True if ready is None else bool(ready)


def deliver_via(
    notifier: Notifier, *, user: User, payload: NotificationPayload
) -> DeliveryOutcome:
    """Ask a notifier for the tri-state outcome the worker needs.

    A plain ``Notifier`` only answers yes/no, and ``False`` is mapped to
    ``permanent``: without an explicit retryable signal we cannot tell a
    timeout from a rejected number, and re-sending on spec risks
    double-delivering. The same reasoning applies to a notifier that
    raises — adapters are contracted not to, so an exception is a bug to
    fix rather than a blip to ride out.
    """
    deliver = getattr(notifier, "deliver", None)
    try:
        if deliver is None:
            sent = notifier.send(user=user, payload=payload)
            return DeliveryOutcome.delivered if sent else DeliveryOutcome.permanent
        outcome: DeliveryOutcome = deliver(user=user, payload=payload)
    except Exception:  # noqa: BLE001 — a bad notifier must not kill the worker
        logger.exception(
            "notifier_failed",
            extra={
                "channel": getattr(notifier, "channel", None),
                "user_id": str(user.id),
            },
        )
        return DeliveryOutcome.permanent
    return outcome


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

    @property
    def ready(self) -> bool:
        from werefa.core.config import settings

        return bool(settings.emails_enabled)

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        return self.deliver(user=user, payload=payload) is DeliveryOutcome.delivered

    def deliver(
        self, *, user: User, payload: NotificationPayload
    ) -> DeliveryOutcome:
        from werefa.core.config import settings
        from werefa.utils import (
            generate_queue_notification_email,
            queue_notification_subject,
            send_email,
            ticket_deep_link,
        )

        if not settings.emails_enabled:
            return DeliveryOutcome.permanent
        if not user.email:
            return DeliveryOutcome.permanent
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
            # SMTP failures are overwhelmingly transient (greylisting,
            # connection resets, a relay briefly over quota), so this is
            # the one place worth another go.
            logger.exception(
                "notification_email_send_failed",
                extra={"user_id": str(user.id), "kind": payload.kind.value},
            )
            return DeliveryOutcome.transient
        return DeliveryOutcome.delivered


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
    """Real SMS delivery through the configured gateway (FR-07).

    Everything vendor-specific lives behind ``SmsProvider``
    (``notifications/infrastructure/sms``); this class only decides
    *whether* a text can be sent and turns the gateway's richer outcome
    back into the boolean the dispatcher wants.

    Three things make it "cannot deliver" — no gateway configured, no
    usable phone number, or a gateway that declined. All three log a
    distinct reason, because "SMS never arrives" is otherwise
    indistinguishable from "the user doesn't have SMS in their prefs".
    """

    channel = NotificationChannel.sms

    def __init__(self, provider: SmsProvider | None = None) -> None:
        # Injected in tests; otherwise resolved per send from the cached
        # module-level provider so ``set_sms_provider`` takes effect
        # without rebuilding the notifier registry.
        self._provider = provider

    def _resolve_provider(self) -> SmsProvider:
        if self._provider is not None:
            return self._provider
        from werefa.notifications.infrastructure.sms import get_sms_provider

        return get_sms_provider()

    @property
    def ready(self) -> bool:
        """Whether a gateway is configured at all.

        Asked by the dispatcher *before* it decides to defer SMS, so an
        `SMS_PROVIDER=disabled` deployment keeps falling through to the
        next channel inline instead of round-tripping through the worker
        to learn the same thing.
        """
        return bool(self._resolve_provider().configured)

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        return self.deliver(user=user, payload=payload) is DeliveryOutcome.delivered

    def deliver(
        self, *, user: User, payload: NotificationPayload
    ) -> DeliveryOutcome:
        from werefa.core.config import settings
        from werefa.notifications.infrastructure.sms import (
            SmsMessage,
            render_sms_body,
            to_e164,
        )
        from werefa.utils import ticket_deep_link

        provider = self._resolve_provider()
        if not provider.configured:
            logger.info(
                "notification_sms_skipped",
                extra={
                    "user_id": str(user.id),
                    "reason": "provider_not_configured",
                    "provider": provider.name,
                },
            )
            # Nothing to retry: a gateway does not configure itself.
            return DeliveryOutcome.permanent

        to = to_e164(
            getattr(user, "phone_number", None),
            default_country_code=settings.SMS_DEFAULT_COUNTRY_CODE,
        )
        if to is None:
            logger.info(
                "notification_sms_skipped",
                extra={
                    "user_id": str(user.id),
                    "reason": "no_usable_phone_number",
                },
            )
            return DeliveryOutcome.permanent

        ticket_link = (
            ticket_deep_link(str(payload.ticket_id))
            if settings.SMS_INCLUDE_TICKET_LINK and payload.ticket_id is not None
            else None
        )
        message = SmsMessage(
            to=to,
            body=render_sms_body(
                body=payload.body,
                brand=settings.BRAND_NAME,
                ticket_link=ticket_link,
                max_chars=settings.SMS_MAX_BODY_CHARS,
            ),
            # Stable per ticket+kind, so a gateway that de-duplicates won't
            # double-text someone when a queue mutation replays.
            idempotency_key=(
                f"{payload.ticket_id}:{payload.kind.value}"
                if payload.ticket_id is not None
                else None
            ),
        )

        try:
            result = provider.send(message)
        except Exception:
            # Adapters are contracted not to raise, but a third-party
            # client can still surprise us and a text message must never
            # take down a queue mutation.
            logger.exception(
                "notification_sms_provider_crashed",
                extra={"user_id": str(user.id), "provider": provider.name},
            )
            # Treated as permanent rather than transient: the adapter
            # broke its own contract, so we have no idea whether the text
            # went out, and retrying could double-charge and double-text.
            return DeliveryOutcome.permanent

        if result.accepted:
            logger.info(
                "notification_sms_delivered",
                extra={
                    "user_id": str(user.id),
                    "kind": payload.kind.value,
                    "provider": result.provider,
                    "provider_message_id": result.provider_message_id,
                },
            )
            return DeliveryOutcome.delivered

        logger.warning(
            "notification_sms_failed",
            extra={
                "user_id": str(user.id),
                "kind": payload.kind.value,
                "provider": result.provider,
                "outcome": result.outcome.value,
                "retryable": result.retryable,
                "error_code": result.error_code,
                "error_detail": result.error_detail,
            },
        )
        # ``retryable`` is the adapters' existing transient/permanent
        # split (SmsOutcome.unavailable vs rejected) — until now it was
        # only ever logged.
        return (
            DeliveryOutcome.transient
            if result.retryable
            else DeliveryOutcome.permanent
        )


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
