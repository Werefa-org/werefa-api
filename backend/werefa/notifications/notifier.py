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
from dataclasses import dataclass, replace
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

    notification_id: uuid.UUID | None = None
    """Ledger row this send belongs to, stamped on by the delivery worker.

    Carried so a gateway that issues delivery receipts can be told which
    row to credit when the carrier reports back — Twilio echoes the
    ``StatusCallback`` URL verbatim, so the id travels in it and comes
    home in the webhook. ``None`` everywhere the send owns no row (the
    email copy of a queue-critical alert), and ``None`` on the request
    thread too: ``dispatch`` writes the row *after* it decides the
    channel, so only :func:`deliver_job` can fill this in.

    Correlating this way rather than by storing the gateway's message id
    first is deliberate: the receipt for a fast carrier can beat our own
    commit of the id, and a webhook that cannot find its row is a
    delivery we silently fail to record.
    """

    def with_default_time(self) -> NotificationPayload:
        if self.occurred_at is not None:
            return self
        return replace(self, occurred_at=utcnow())

    def for_ledger_row(
        self, notification_id: uuid.UUID | None
    ) -> NotificationPayload:
        """Tie this payload to the row whose fate the send decides."""
        if notification_id is None or notification_id == self.notification_id:
            return self
        return replace(self, notification_id=notification_id)


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

    accepted = "accepted"
    """The gateway took it and owes us a delivery receipt.

    Distinct from ``delivered`` in exactly one respect, and it is the
    respect that matters: nobody has confirmed the message reached a
    handset. The worker treats it like ``delivered`` for control flow —
    the send left successfully, so there is nothing to retry and no
    fall-through — and records it as ``NotificationStatus.sent`` instead,
    which the receipt webhook later resolves.

    Only a notifier that has genuinely asked for a receipt may return
    this. Answering ``accepted`` for a gateway that never calls back
    would leave the row stuck at ``sent`` forever, which is a worse lie
    than the optimistic ``delivered`` it replaced.
    """


SENT_OUTCOMES: frozenset[DeliveryOutcome] = frozenset(
    {DeliveryOutcome.delivered, DeliveryOutcome.accepted}
)
"""Outcomes that mean "the message left, stop looking for another channel".

The pair exists so callers ask "did this go out?" once, instead of every
site that used to compare against ``delivered`` growing a second arm and
one of them being forgotten.
"""


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

    Unlike the queue fan-out, this notifier's answer is load-bearing. The
    dispatcher treats ``True`` as *delivered*: it stops walking the
    preference list and writes ``delivered`` to the ledger, so SMS and
    email are never attempted. Reporting success for a publish that has
    merely been scheduled therefore costs the customer every channel at
    once — the alert is recorded as sent and nothing arrives anywhere.

    That is exactly what the old ``loop.create_task`` here did. It is not
    thread-safe, and every sync ``def`` route reaching dispatch runs on a
    worker thread: the task was appended to the loop's ready queue without
    waking the loop, ``send`` returned ``True``, and the "you're next"
    alert was booked as delivered while the loop slept. The ``except
    RuntimeError`` below it never helped, because from a foreign thread
    ``create_task`` does not raise — it succeeds and does nothing.

    :func:`publish_and_confirm` waits, bounded, for the publish to actually
    complete — but completing is still not the same as arriving, which is
    the second half of the same bug and took longer to see. A publish to a
    service line **nobody is subscribed to** completes perfectly and
    reaches nobody, so "the fan-out happened" was still being read as "the
    customer was told". With the default preferences
    (``websocket, email, logger``) that is every customer whose app is
    closed: the alert was booked ``delivered``, SMS was never tried, and
    FR-05 liveness then flagged them for not answering it.

    So the audience decides the answer, and there are three:

    * **Subscribers took it** — delivered, in the strongest sense this
      channel can offer.
    * **Provably nobody** (zero subscribers, no Redis) — *not* delivered.
      The dispatcher falls through to a channel that can still reach them.
      This is the only honest reading, and it is the one that gets the
      customer an SMS.
    * **Cannot know** (behind Redis, subscribers may be on another
      replica) — :attr:`DeliveryOutcome.accepted`. The event left, nobody
      can vouch for who received it, and the ledger says so by holding the
      row at ``sent``. Falling through here instead would double-notify
      every app user in a multi-replica deployment; claiming delivery
      would be the same lie in the other direction. ``sent`` ages into
      ``not_reached`` if it is never bettered, so liveness still stops
      blaming a customer we cannot show we reached.
    """

    channel = NotificationChannel.websocket

    def send(self, *, user: User, payload: NotificationPayload) -> bool:
        return self.deliver(user=user, payload=payload) in SENT_OUTCOMES

    def deliver(
        self, *, user: User, payload: NotificationPayload
    ) -> DeliveryOutcome:
        # Imported lazily so this module stays importable without the
        # realtime package being initialised (e.g. in pure-rule tests).
        from werefa.realtime.domain.events import NotifyEventV1
        from werefa.realtime.notify import publish_and_confirm

        if payload.ticket_id is None or payload.service_item_id is None:
            return DeliveryOutcome.permanent

        event = NotifyEventV1(
            ticket_id=payload.ticket_id,
            service_item_id=payload.service_item_id,
            kind=payload.kind.value,  # type: ignore[arg-type]
            position=payload.position or 1,
            body=payload.body,
            occurred_at=payload.occurred_at or utcnow(),
        )
        outcome = publish_and_confirm(
            payload.service_item_id,
            event.model_dump_json(),
            what="Ticket alert",
        )
        if not outcome.published:
            return DeliveryOutcome.permanent
        if outcome.reached_nobody:
            logger.info(
                "notification_websocket_no_subscribers",
                extra={
                    "user_id": str(user.id),
                    "kind": payload.kind.value,
                    "service_item_id": str(payload.service_item_id),
                },
            )
            # Permanent rather than transient: their app is not connected,
            # and retrying this same channel on a timer would not change
            # that. Falling through now is what reaches them.
            return DeliveryOutcome.permanent
        if outcome.audience_unknown:
            return DeliveryOutcome.accepted
        return DeliveryOutcome.delivered


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
        # The relay took it; whether it reached an inbox is a bounce that
        # arrives as its own mail hours later, keyed to nothing we hold.
        # Same class of claim as Twilio's 201 and a subscriber-less
        # publish, so it gets the same answer rather than a third one.
        return DeliveryOutcome.accepted


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

    A fourth answer sits between success and failure and is the reason
    :class:`DeliveryOutcome` grew ``accepted``: a gateway asked for a
    delivery receipt has told us it *took* the message, nothing more.
    Reporting that as delivery is how a text to a disconnected number
    came to look identical to one the customer acted on.
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
        # ``accepted`` counts: the text is with the carrier. The bool
        # contract only asks whether this channel took the message, and a
        # receipt we have not received yet is not a reason to also send an
        # email — see ``SENT_OUTCOMES``.
        return self.deliver(user=user, payload=payload) in SENT_OUTCOMES

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
            # What the gateway should quote back on a delivery receipt.
            # ``None`` when this send owns no ledger row, in which case
            # there is nothing a receipt could update and the adapter
            # asks for none.
            receipt_reference=(
                str(payload.notification_id)
                if payload.notification_id is not None
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
                    "receipt_expected": result.receipt_expected,
                },
            )
            # A gateway that owes us a receipt has told us only that it
            # took the message. Saying ``delivered`` here is what made
            # "Twilio returned 201" and "it reached a phone" the same
            # thing in the ledger, and the liveness flow then read our own
            # optimism back as evidence the customer had been warned.
            return (
                DeliveryOutcome.accepted
                if result.receipt_expected
                else DeliveryOutcome.delivered
            )

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
