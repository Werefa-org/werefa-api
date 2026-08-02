"""Notification dispatch + ledger + smart-alert orchestration (FR-07).

Dispatch is still synchronous for channels that deliver in-process
(websocket, push, logger) — they cost microseconds and their result can
honestly be written straight into the ledger. Channels that leave the
machine (SMS, email) are handed to the delivery worker instead, because
a gateway round-trip has no useful upper bound and used to be paid by
the HTTP request.

That split has one consequence worth stating plainly: for a deferred
channel the ledger row is written ``queued`` and *resolved later* by
:func:`deliver_job`, which also owns the fall-through to the next
preference — only the worker can know whether SMS actually worked.

Even the worker only knows half of it. A gateway answers "I took this",
not "they got this", so where delivery receipts are configured the row is
resolved to ``sent`` and a third writer — :func:`record_delivery_receipt`,
called from the webhook minutes later — settles it. The three writers see
the row in different states and are allowed different things; the rules
live in :mod:`werefa.notifications.domain.receipts` rather than being
spread across the functions that apply them.

Jobs are handed over on ``after_commit`` rather than at dispatch time.
Two reasons: the worker reads the ledger row from its own session, so
the row has to exist; and a transaction that rolls back must not have
texted anyone about a ticket that no longer exists.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import ClassVar

from fastapi import HTTPException, status
from sqlalchemy import event, func
from sqlalchemy.orm import Session as SASession
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.core.db import engine
from werefa.notifications.domain.receipts import (
    RECEIPT_CHANNELS,
    ReceiptOutcome,
    decide_receipt,
    reach_of,
)
from werefa.notifications.domain.retry import RetryPolicy
from werefa.notifications.domain.triggers import decide_alert
from werefa.notifications.infrastructure.delivery import (
    DeliveryAttempt,
    DeliveryJob,
    DeliveryQueue,
)
from werefa.notifications.notifier import (
    SENT_OUTCOMES,
    DeliveryOutcome,
    NotificationPayload,
    Notifier,
    channel_is_ready,
    default_registry,
    deliver_via,
)
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationReach,
    NotificationStatus,
    TicketStatus,
)
from werefa.shared.models import (
    Notification,
    NotificationPrefsUpdate,
    QueueEntry,
    User,
    utcnow,
)

logger = logging.getLogger(__name__)

# Queue-critical alerts always attempt email when it is in the user's
# prefs, even if websocket already delivered (in-app + inbox + mail).
EMAIL_COPY_KINDS: frozenset[NotificationKind] = frozenset(
    {
        NotificationKind.head_to_counter,
        NotificationKind.you_are_next,
        NotificationKind.now_serving,
        NotificationKind.liveness_ping_request,
        NotificationKind.liveness_stale,
        NotificationKind.liveness_hold,
        NotificationKind.line_chat_update,
        NotificationKind.queue_cleared,
    }
)

# Module-level registry mutable for tests via ``set_registry``. The
# default registry is rebuilt lazily so importing this module from a
# pure-rule test that doesn't need realtime stays cheap.
_registry: dict[NotificationChannel, Notifier] | None = None


def get_registry() -> dict[NotificationChannel, Notifier]:
    global _registry
    if _registry is None:
        _registry = default_registry()
    return _registry


def set_registry(registry: dict[NotificationChannel, Notifier] | None) -> None:
    """Test seam: swap the registry for fakes; pass ``None`` to reset."""
    global _registry
    _registry = registry


# Channels whose delivery involves a third party we cannot bound. These are
# the ones lifted off the request path; everything else stays inline.
REMOTE_CHANNELS: frozenset[NotificationChannel] = frozenset(
    {NotificationChannel.sms, NotificationChannel.email}
)

# Same lazy-singleton-with-a-setter shape as the registry above, for the
# same reason: importing this module must not start threads.
_delivery_queue: DeliveryQueue | None = None


def get_delivery_queue() -> DeliveryQueue:
    global _delivery_queue
    if _delivery_queue is None:
        _delivery_queue = DeliveryQueue(
            deliver_job,
            policy=RetryPolicy.from_settings(),
            max_size=settings.NOTIFICATION_DELIVERY_QUEUE_MAX,
            workers=settings.NOTIFICATION_DELIVERY_WORKERS,
            shed_max=settings.NOTIFICATION_DELIVERY_SHED_MAX,
            shed_ttl_seconds=settings.NOTIFICATION_DELIVERY_SHED_TTL_SECONDS,
        )
    return _delivery_queue


def set_delivery_queue(queue: DeliveryQueue | None) -> None:
    """Test seam: swap in an inline or recording queue; ``None`` resets.

    Stops the queue being replaced so a swapped-out worker pool does not
    keep draining jobs behind the new one's back.
    """
    global _delivery_queue
    if _delivery_queue is not None and _delivery_queue is not queue:
        _delivery_queue.stop(timeout=1.0)
    _delivery_queue = queue


# The worker cannot use the request's Session — it is closed once the
# response is sent (same trap ``run_evaluate_smart_alerts_for_service_line``
# documents), so every job opens its own.
_session_factory: Callable[[], Session] | None = None


def set_delivery_session_factory(
    factory: Callable[[], Session] | None,
) -> None:
    """Test seam: let a delivery job run against a stub session."""
    global _session_factory
    _session_factory = factory


def _open_session() -> Session:
    if _session_factory is not None:
        return _session_factory()
    return Session(engine)


def _user_prefs(user: User) -> list[NotificationChannel]:
    raw = user.notification_prefs or list(settings.NOTIFICATION_DEFAULT_PREFS)
    out: list[NotificationChannel] = []
    seen: set[NotificationChannel] = set()
    for key in raw:
        try:
            channel = NotificationChannel(key)
        except ValueError:
            continue
        if channel in seen:
            continue
        seen.add(channel)
        out.append(channel)
    # Always retain the logger backstop so every dispatch yields *some*
    # ledger row, even when the user explicitly disabled every other
    # channel.
    if NotificationChannel.logger not in seen:
        out.append(NotificationChannel.logger)
    return out


def _email_is_a_copy(
    kind: NotificationKind, prefs: list[NotificationChannel]
) -> bool:
    """Is email going out as an extra *copy* rather than as the primary?

    When it is, ``dispatch`` steps over email in the preference walk and
    in every fall-through list, and sends it separately with no ledger row
    of its own — see :func:`_try_email_copy`.
    """
    return kind in EMAIL_COPY_KINDS and NotificationChannel.email in prefs


def delivery_fallbacks(
    user: User,
    *,
    channel: NotificationChannel,
    kind: NotificationKind,
) -> tuple[NotificationChannel, ...]:
    """Preferences to try after ``channel`` fails for good.

    Reconstructs what ``dispatch`` put on the job when it queued the row.
    Built from the user's *current* prefs, which is the only list we have
    — a channel they have since dropped yields ``()``, meaning the queued
    channel is tried on its own rather than falling through to something
    the user no longer asked for.
    """
    prefs = _user_prefs(user)
    if channel not in prefs:
        return ()
    rest = prefs[prefs.index(channel) + 1 :]
    if _email_is_a_copy(kind, prefs):
        rest = [c for c in rest if c is not NotificationChannel.email]
    return tuple(rest)


def _persist_ledger(
    session: Session,
    *,
    user_id: uuid.UUID,
    ticket_id: uuid.UUID | None,
    kind: NotificationKind,
    body: str,
    channel: NotificationChannel,
    status_value: NotificationStatus,
    position: int | None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        ticket_id=ticket_id,
        kind=kind.value,
        body=body,
        channel=channel.value,
        status=status_value.value,
        position=position,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


# --- hand-off to the delivery worker ------------------------------------

_PENDING_KEY = "werefa_pending_deliveries"


def _hand_off(session: Session, job: DeliveryJob) -> None:
    """Queue ``job`` once the caller's transaction commits.

    Sessions in component tests are hand-rolled fakes with no SQLAlchemy
    event machinery — and no transaction to wait on either — so those
    hand over immediately.
    """
    info = getattr(session, "info", None)
    if info is None:
        _submit(job)
        return
    info.setdefault(_PENDING_KEY, []).append(job)


@event.listens_for(SASession, "after_commit")
def _submit_pending_deliveries(session: SASession) -> None:
    for job in session.info.pop(_PENDING_KEY, ()):
        _submit(job)


@event.listens_for(SASession, "after_rollback")
def _drop_pending_deliveries(session: SASession) -> None:
    # The ticket the alert was about never happened.
    session.info.pop(_PENDING_KEY, None)


def submit_delivery_job(job: DeliveryJob) -> None:
    """Hand ``job`` to the worker now, with no transaction to wait for.

    ``dispatch`` never does this — its ledger row is still uncommitted, so
    it goes through :func:`_hand_off` instead. Reconciliation does: its
    rows were committed long ago, by a process that is no longer running.
    """
    _submit(job)


def _submit(job: DeliveryJob) -> None:
    queue = get_delivery_queue()
    if queue.submit(job):
        return
    logger.error(
        "notification_delivery_queue_full",
        extra={"channel": job.channel.value, "user_id": str(job.user_id)},
    )
    # Order matters. Settle the row on a local channel *first*, then park
    # the real one — parking first would race a promoted job into
    # upgrading the row, only for the fallback to overwrite it.
    _shed_to_local_channel(job)
    parked = queue.defer(
        replace(
            job,
            # The fall-through already happened above; a promoted job that
            # fails must not deliver on those channels a second time.
            fallback_channels=(),
            upgrade_only=True,
        )
    )
    if not parked:
        logger.error(
            "notification_delivery_shed_dropped",
            extra={"channel": job.channel.value, "user_id": str(job.user_id)},
        )


def _shed_to_local_channel(job: DeliveryJob) -> None:
    """Queue full: deliver on the best *in-process* preference instead.

    A full queue means a gateway is wedged and work is piling up, and
    this runs on the request thread — so the one thing it must not do is
    call another provider. Handing the job to :func:`deliver_job` here
    would do exactly that whenever a remote channel sits in the
    fall-through list (prefs like ``["sms", "email", ...]``), putting an
    unbounded network wait straight back on the response and, on
    ``join-with-files``, back on the event loop.

    So remote fallbacks are *skipped*, never sent. The alert lands on an
    in-process channel — in practice the ``logger`` backstop, which
    ``_user_prefs`` always keeps — and the ledger records whatever
    actually delivered, or ``failed`` if nothing did.

    This is the *floor*, not the final answer: the caller parks the shed
    remote send on the queue afterwards, so it still goes out once
    capacity returns and upgrades the row if it lands.
    """
    registry = get_registry()
    candidates: list[tuple[NotificationChannel, Notifier]] = []
    for channel in job.fallback_channels:
        if channel in REMOTE_CHANNELS:
            continue
        notifier = registry.get(channel)
        if notifier is not None:
            candidates.append((channel, notifier))

    if not candidates and job.notification_id is None:
        # An email copy owns no ledger row, so there is nothing to record
        # and no reason to open a session.
        return

    with _open_session() as session:
        user = session.get(User, job.user_id)
        if user is None or not user.is_active:
            _resolve_ledger_row(
                session,
                job.notification_id,
                channel=job.channel,
                status_value=NotificationStatus.failed,
            )
            return

        for channel, notifier in candidates:
            outcome = deliver_via(notifier, user=user, payload=job.payload)
            if outcome in SENT_OUTCOMES:
                _resolve_ledger_row(
                    session,
                    job.notification_id,
                    channel=channel,
                    status_value=_status_for(outcome),
                )
                return

        _resolve_ledger_row(
            session,
            job.notification_id,
            # Names a channel that was really tried, or the shed one when
            # there was no local preference to fall back to.
            channel=candidates[-1][0] if candidates else job.channel,
            status_value=NotificationStatus.failed,
        )


def _status_for(outcome: DeliveryOutcome) -> NotificationStatus:
    """Ledger status for a send that left the machine successfully.

    The two differ by exactly one thing: whether anybody has promised to
    tell us what happened next. ``accepted`` comes from a gateway that
    owes us a delivery receipt, so the row waits at ``sent`` for it
    instead of claiming an arrival nobody has witnessed.
    """
    return (
        NotificationStatus.sent
        if outcome is DeliveryOutcome.accepted
        else NotificationStatus.delivered
    )


def _resolve_ledger_row(
    session: Session,
    notification_id: uuid.UUID | None,
    *,
    channel: NotificationChannel,
    status_value: NotificationStatus,
    upgrade: bool = False,
) -> None:
    """Flip a ``queued`` row to its final channel and status.

    ``queued`` is the only state this may overwrite. A row that already
    reads ``delivered`` or ``failed`` has been settled by somebody — the
    original worker finishing just after reconciliation handed the job out
    again, a second replica, a job that outlived its own process — and the
    later writer is not the one holding the truth. Refusing here is what
    stops a reconciled retry from stamping ``failed`` over a delivery that
    really happened.

    ``upgrade`` is the one documented exception, and only ever toward
    ``delivered``: a shed job settles the row on a local fallback, and the
    parked remote send that lands afterwards is *supposed* to move it to
    the channel the user actually ranked higher.

    That the exception stops at ``delivered`` now does a second job. A
    parked SMS that comes back ``accepted`` would want to write ``sent``,
    and ``sent`` is *weaker* than the local delivery already recorded —
    trading a channel the customer demonstrably received for one that
    might yet fail. So it is refused like any other late writer, and the
    receipt that follows finds a row that is no longer SMS's to settle
    (:func:`record_delivery_receipt` re-checks the channel for exactly
    this reason).

    ``notification_id`` is ``None`` for the email copy, which never owned
    a row — see :func:`_try_email_copy`.
    """
    if notification_id is None:
        return
    row = session.get(Notification, notification_id)
    if row is None:
        # The ticket (and its cascade) went away while the send was in
        # flight, or the job outlived its transaction.
        logger.warning(
            "notification_delivery_row_missing",
            extra={"notification_id": str(notification_id)},
        )
        return
    settled = row.status != NotificationStatus.queued.value
    if settled and not (upgrade and status_value is NotificationStatus.delivered):
        logger.warning(
            "notification_delivery_row_already_settled",
            extra={
                "notification_id": str(notification_id),
                "current_status": row.status,
                "attempted_status": status_value.value,
            },
        )
        return
    row.channel = channel.value
    row.status = status_value.value
    session.add(row)
    session.commit()


def _mark_attempt(session: Session, notification_id: uuid.UUID | None) -> None:
    """Record that this row's message is about to be handed to a gateway.

    Committed *before* the provider call, on purpose. The ledger cannot
    tell us afterwards whether a send that died mid-flight reached anyone
    — the process that knew is gone — so the only honest signal is one
    written while we still had the chance. ``delivery_attempts == 0`` then
    means "provably never sent", which is the only case reconciliation is
    allowed to re-send.

    Best-effort: a counter we failed to bump must not stop the send. The
    cost of losing it is that a crashed attempt looks un-attempted and may
    be re-sent once, which is exactly where we were before.
    """
    if notification_id is None:
        return
    row = session.get(Notification, notification_id)
    if row is None:
        return
    row.delivery_attempts += 1
    session.add(row)
    try:
        session.commit()
    except Exception:  # noqa: BLE001 — never block a send on bookkeeping
        logger.exception(
            "notification_delivery_attempt_not_recorded",
            extra={"notification_id": str(notification_id)},
        )
        session.rollback()


def _record_failure(
    session: Session,
    job: DeliveryJob,
    *,
    channel: NotificationChannel,
) -> None:
    """Mark the row failed, unless a fallback already settled it.

    A shed job's row records a local channel that really delivered. The
    parked remote retry is a bonus attempt: if it works the row is
    upgraded to that channel, and if it does not, the earlier delivery
    still stands.
    """
    if job.upgrade_only:
        logger.warning(
            "notification_delivery_shed_retry_failed",
            extra={
                "channel": channel.value,
                "user_id": str(job.user_id),
            },
        )
        return
    _resolve_ledger_row(
        session,
        job.notification_id,
        channel=channel,
        status_value=NotificationStatus.failed,
    )


def deliver_job(job: DeliveryJob) -> DeliveryAttempt:
    """Run one queued send. This is the delivery worker's whole payload.

    Owns the part of channel fall-through that used to live in the
    dispatcher's loop: on a permanent failure it walks
    ``fallback_channels`` in order, and only records ``failed`` once the
    list is exhausted. A transient failure returns without touching the
    ledger, leaving the row ``queued`` for the retry.

    Every send that leaves the machine is announced in the ledger first
    (:func:`_mark_attempt`). Getting killed between that write and the
    provider's answer is precisely the case reconciliation must not
    re-send, and this is the only place that can leave a trace of it.
    """
    registry = get_registry()
    with _open_session() as session:
        user = session.get(User, job.user_id)
        if user is None or not user.is_active:
            _record_failure(session, job, channel=job.channel)
            return DeliveryAttempt(DeliveryOutcome.permanent)

        channel = job.channel
        remaining = list(job.fallback_channels)
        # A channel with no registered notifier is skipped rather than
        # counted as a failed attempt — same as the dispatch loop — so the
        # row ends up naming a channel that was really tried.
        last_tried = job.channel
        while True:
            notifier = registry.get(channel)
            if notifier is not None:
                last_tried = channel
                if channel in REMOTE_CHANNELS:
                    # Only channels that reach a third party can leave a
                    # message we cannot see the fate of. An in-process one
                    # settles the row in this same session or not at all.
                    _mark_attempt(session, job.notification_id)
                outcome = deliver_via(
                    notifier,
                    user=user,
                    # Only here does a send know which row it answers for,
                    # which is what a gateway needs in order to quote it
                    # back on a delivery receipt.
                    payload=job.payload.for_ledger_row(job.notification_id),
                )

                if outcome in SENT_OUTCOMES:
                    _resolve_ledger_row(
                        session,
                        job.notification_id,
                        channel=channel,
                        status_value=_status_for(outcome),
                        upgrade=job.upgrade_only,
                    )
                    return DeliveryAttempt(outcome)

                if outcome is DeliveryOutcome.transient and not job.last_attempt:
                    # Resume on *this* channel, which may already be past
                    # the one the job arrived on.
                    return DeliveryAttempt(
                        DeliveryOutcome.transient,
                        retry_with=replace(
                            job,
                            channel=channel,
                            fallback_channels=tuple(remaining),
                        ),
                    )

                if outcome is DeliveryOutcome.transient:
                    logger.warning(
                        "notification_delivery_retries_exhausted",
                        extra={
                            "channel": channel.value,
                            "attempt": job.attempt,
                            "user_id": str(user.id),
                        },
                    )

            if not remaining:
                _record_failure(session, job, channel=last_tried)
                return DeliveryAttempt(DeliveryOutcome.permanent)
            channel = remaining.pop(0)


# --- delivery receipts --------------------------------------------------


def record_delivery_receipt(
    session: Session,
    *,
    notification_id: uuid.UUID,
    receipt: ReceiptOutcome,
    provider_message_id: str | None = None,
    error_code: str | None = None,
) -> Notification | None:
    """Apply a carrier's verdict to the row that send was made for.

    The counterpart to :func:`_resolve_ledger_row`, and deliberately not
    the same function. That one closes a row the *worker* owns and knows
    nothing beyond "the gateway took it"; this one arrives minutes later,
    from outside, on a row that may have moved on since — so the rules
    about what it may overwrite are different, and live in
    :func:`werefa.notifications.domain.receipts.decide_receipt`.

    Returns the row when the receipt changed something, ``None`` when it
    did not. ``None`` is the ordinary case for the intermediate callbacks
    Twilio sends on the way (``sending``, ``sent``) and for duplicates,
    so callers must not read it as a failure — the webhook answers 204
    either way, because asking Twilio to retry a callback we understood
    perfectly well and chose to ignore just brings it back again.
    """
    row = session.get(Notification, notification_id)
    if row is None:
        # The ticket (and its cascade) went away, or the id in the
        # callback URL is not one of ours.
        logger.warning(
            "notification_receipt_row_missing",
            extra={"notification_id": str(notification_id)},
        )
        return None

    channel = _channel_of(row.channel)
    if channel not in RECEIPT_CHANNELS:
        # The send fell through to another channel, or an overload shed
        # settled the row locally. Either way this row is no longer a
        # record of the SMS the carrier is talking about.
        logger.info(
            "notification_receipt_channel_moved_on",
            extra={
                "notification_id": str(notification_id),
                "channel": row.channel,
                "receipt": receipt.value,
            },
        )
        return None

    new_status = decide_receipt(
        current_status=_status_of(row.status),
        current_channel=channel,
        receipt=receipt,
    )

    changed = False
    if provider_message_id and row.provider_message_id != provider_message_id:
        # Recorded even when the status does not move: the first callback
        # is usually an intermediate one, and having the SID on the row
        # from that moment is what makes a support question ("what
        # happened to this alert?") answerable in Twilio's console.
        row.provider_message_id = provider_message_id[:64]
        changed = True
    if new_status is not None:
        if new_status is NotificationStatus.failed:
            row.delivery_error_code = error_code[:16] if error_code else None
        else:
            # A later success clears a code from an earlier attempt, so
            # the row never reads "delivered, because of error 30003".
            row.delivery_error_code = None
        row.status = new_status.value
        changed = True

    if not changed:
        return None

    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info(
        "notification_receipt_recorded",
        extra={
            "notification_id": str(notification_id),
            "kind": row.kind,
            "receipt": receipt.value,
            "status": row.status,
            "error_code": row.delivery_error_code,
        },
    )
    return row


@dataclass(frozen=True)
class PromptDelivery:
    """What became of the last alert of a given kind for one ticket.

    ``reach`` is the answer callers act on; ``channel`` and ``status`` are
    the evidence behind it, carried so a log line can distinguish the
    three very different situations that all reduce to ``not_reached``:

    * ``sms``/``failed`` — a carrier told us it bounced. One customer's
      bad number.
    * ``sms``/``sent`` aged out — no receipt ever came. A *run* of these
      is a status-callback URL that does not resolve, which otherwise
      looks exactly like a line full of unreachable customers.
    * ``logger``/``delivered`` — the customer has no reachable channel at
      all, so the backstop was the only thing that "worked".

    Only the first is really about the customer, and telling them apart
    from the board is impossible without this.
    """

    reach: NotificationReach
    channel: NotificationChannel | None = None
    status: NotificationStatus | None = None

    UNKNOWN: ClassVar[PromptDelivery]
    """Stand-in for a ticket we never prompted — see :func:`alert_reach`."""


PromptDelivery.UNKNOWN = PromptDelivery(NotificationReach.unconfirmed)


def alert_reach(
    session: Session,
    *,
    ticket_ids: list[uuid.UUID],
    kinds: frozenset[NotificationKind],
    now: datetime | None = None,
) -> dict[uuid.UUID, PromptDelivery]:
    """For each ticket, did our most recent alert of these kinds land?

    One query for the whole line rather than one per ticket: the callers
    are the liveness sync loop and the staff board, both of which walk
    every watched ticket on every poll.

    The most recent prompt that actually *decided* something wins —
    ``confirmed`` or ``not_reached``. Rows in between that resolved to
    ``unconfirmed`` are stepped over rather than allowed to overwrite,
    because ``unconfirmed`` is the absence of information and cannot
    displace information we have.

    That distinction is load-bearing, not pedantry. Parking an
    unreachable customer sends them a "your spot is held" notification,
    which is itself a prompt; it lands "delivered" on the websocket
    channel, whose delivery nobody can vouch for. Taking the newest row
    unconditionally would let the hold we granted *because* we could not
    reach them launder the ticket back to "we do not know" — and the
    next window would flag them on exactly the silence the hold existed
    to excuse.

    Row age is supplied along with the pair, because "still waiting on a
    receipt" is only an open question for as long as a receipt could
    plausibly still arrive — see :func:`reach_of` and
    ``NOTIFICATION_RECEIPT_GRACE_SECONDS``.

    A ticket with no matching row is absent from the result; callers read
    that as :attr:`PromptDelivery.UNKNOWN`, since nothing was asked and
    nothing therefore failed.
    """
    if not ticket_ids:
        return {}
    rows = session.exec(
        select(Notification)
        .where(col(Notification.ticket_id).in_(ticket_ids))
        .where(col(Notification.kind).in_([k.value for k in kinds]))
        .order_by(col(Notification.created_at).desc())
    ).all()

    now = now or utcnow()
    grace = settings.NOTIFICATION_RECEIPT_GRACE_SECONDS
    out: dict[uuid.UUID, PromptDelivery] = {}
    for row in rows:
        # Ordered newest first, so the first *decided* hit per ticket is
        # the latest thing we actually know.
        if row.ticket_id is None:
            continue
        if out.get(row.ticket_id, PromptDelivery.UNKNOWN).reach is not (
            NotificationReach.unconfirmed
        ):
            continue
        channel = _channel_of(row.channel)
        status = _status_of(row.status)
        entry = PromptDelivery(
            reach=reach_of(
                channel,
                status,
                age_seconds=_row_age_seconds(row.created_at, now),
                resolution_grace_seconds=grace,
            ),
            channel=channel,
            status=status,
        )
        # Keep the newest row's evidence when nothing is decided, so the
        # diagnostic fields describe the latest attempt either way.
        if row.ticket_id not in out or entry.reach is not (
            NotificationReach.unconfirmed
        ):
            out[row.ticket_id] = entry
    return out


def _row_age_seconds(
    created_at: datetime | None, now: datetime
) -> float | None:
    """Age of a ledger row, or ``None`` when it cannot be measured.

    A row with no ``created_at`` yields ``None``, which keeps its pending
    status readable as an open question rather than ageing it out on a
    clock we do not have. Naive timestamps are treated as ``now``'s zone —
    the column is ``timezone=True``, but an older build or a test stub may
    have written one without, and subtracting mixed awareness raises.
    """
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=now.tzinfo)
    return (now - created_at).total_seconds()


def _channel_of(raw: str) -> NotificationChannel | None:
    """The ledger stores plain strings, so a value this build does not
    know about (a rollback, a hand-edited row) must read as ``None``
    rather than raise inside a webhook or a queue poll."""
    try:
        return NotificationChannel(raw)
    except ValueError:
        return None


def _status_of(raw: str) -> NotificationStatus | None:
    try:
        return NotificationStatus(raw)
    except ValueError:
        return None


def _defers(channel: NotificationChannel, notifier: Notifier) -> bool:
    """Should ``channel`` be handed to the worker instead of sent now?

    A channel that reports itself unready (no SMS gateway configured, no
    SMTP host) is *not* deferred: sending it to the worker would write a
    ``queued`` row only to walk it back a moment later, where today the
    dispatcher just falls through. ``ready`` lives on the notifier so this
    stays free of any vendor knowledge.
    """
    return (
        settings.NOTIFICATION_DELIVERY_ASYNC
        and channel in REMOTE_CHANNELS
        and channel_is_ready(notifier)
    )


def _try_email_copy(
    registry: dict[NotificationChannel, Notifier],
    *,
    session: Session,
    user: User,
    payload: NotificationPayload,
) -> None:
    """Send email without changing the primary ledger channel."""
    from werefa.core.config import settings

    if not settings.emails_enabled:
        return
    if payload.kind not in EMAIL_COPY_KINDS:
        return
    prefs = _user_prefs(user)
    if NotificationChannel.email not in prefs:
        return
    notifier = registry.get(NotificationChannel.email)
    if notifier is None:
        return
    if _defers(NotificationChannel.email, notifier):
        # No ledger row of its own — the copy has never had one, so the
        # worker has nothing to resolve and nothing to fall through to.
        _hand_off(
            session,
            DeliveryJob(
                user_id=user.id,
                channel=NotificationChannel.email,
                payload=payload,
            ),
        )
        return
    try:
        notifier.send(user=user, payload=payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "notification_email_copy_failed",
            extra={"kind": payload.kind.value, "user_id": str(user.id)},
        )


def dispatch(
    session: Session,
    *,
    user: User,
    payload: NotificationPayload,
) -> Notification | None:
    """Try each preferred channel until one accepts; record the result.

    In-process channels are still tried inline, so their outcome lands in
    the ledger synchronously. The first *remote* channel reached instead
    ends the loop: the row is written ``queued`` on that channel and the
    worker resolves it, carrying the untried preferences as
    ``fallback_channels`` so fall-through survives the hand-off.

    Returns the persisted ``Notification`` row (or ``None`` when the user
    has no usable channels — a degenerate case impossible in practice
    because ``logger`` is always retained).
    """
    payload = payload.with_default_time()
    registry = get_registry()
    prefs = _user_prefs(user)
    defer_email = _email_is_a_copy(payload.kind, prefs)

    def _still_to_try(after: int) -> tuple[NotificationChannel, ...]:
        return tuple(
            c
            for c in prefs[after + 1 :]
            if not (defer_email and c == NotificationChannel.email)
        )

    delivered_via: NotificationChannel | None = None
    delivered_status = NotificationStatus.delivered
    queued_via: NotificationChannel | None = None
    fallbacks: tuple[NotificationChannel, ...] = ()
    skipped: list[NotificationChannel] = []
    for index, channel in enumerate(prefs):
        if defer_email and channel == NotificationChannel.email:
            continue
        notifier = registry.get(channel)
        if notifier is None:
            continue
        if _defers(channel, notifier):
            queued_via = channel
            fallbacks = _still_to_try(index)
            break
        # The tri-state, not the boolean: an in-process channel can also
        # take a message without anybody being able to say a person
        # received it (a websocket publish behind Redis), and the ledger
        # has somewhere to put that now.
        outcome = deliver_via(notifier, user=user, payload=payload)
        if outcome in SENT_OUTCOMES:
            delivered_via = channel
            delivered_status = _status_for(outcome)
            break
        skipped.append(channel)

    if queued_via is not None:
        final_channel = queued_via
        final_status = NotificationStatus.queued
    else:
        final_status = (
            delivered_status
            if delivered_via is not None
            else NotificationStatus.failed
        )
        final_channel = delivered_via or (
            skipped[-1] if skipped else NotificationChannel.logger
        )

    row = _persist_ledger(
        session,
        user_id=user.id,
        ticket_id=payload.ticket_id,
        kind=payload.kind,
        body=payload.body,
        channel=final_channel,
        status_value=final_status,
        position=payload.position,
    )
    if queued_via is not None:
        _hand_off(
            session,
            DeliveryJob(
                user_id=user.id,
                channel=queued_via,
                payload=payload,
                notification_id=row.id,
                fallback_channels=fallbacks,
            ),
        )
    if defer_email:
        _try_email_copy(registry, session=session, user=user, payload=payload)
    return row


STAFF_YOU_ARE_NEXT_BODY = "You are next in the queue!!!!"


def notify_ticket_staff_you_are_next(
    session: Session,
    *,
    ticket: QueueEntry,
    service_item_id: uuid.UUID,
) -> Notification | None:
    """Staff-triggered alert: customer is next in line (app users only)."""
    if ticket.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Walk-in customers cannot receive app notifications.",
        )
    if ticket.status != TicketStatus.waiting.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only waiting customers can be notified.",
        )
    user = session.get(User, ticket.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This customer cannot receive notifications.",
        )
    pos = _ticket_position(session, ticket)
    result = dispatch(
        session,
        user=user,
        payload=NotificationPayload(
            kind=NotificationKind.you_are_next,
            body=STAFF_YOU_ARE_NEXT_BODY,
            ticket_id=ticket.id,
            service_item_id=service_item_id,
            position=pos,
        ),
    )
    ticket.last_alert_position = 1
    session.add(ticket)
    session.commit()
    if result is not None:
        session.refresh(result)
    return result


def notify_ticket_now_serving(
    session: Session,
    *,
    ticket: QueueEntry,
    service_item_id: uuid.UUID,
) -> Notification | None:
    """Alert the customer whose ticket was just called to the counter."""
    if ticket.user_id is None:
        return None
    user = session.get(User, ticket.user_id)
    if user is None or not user.is_active:
        return None
    return dispatch(
        session,
        user=user,
        payload=NotificationPayload(
            kind=NotificationKind.now_serving,
            body="You're being served now — please come to the counter.",
            ticket_id=ticket.id,
            service_item_id=service_item_id,
            position=1,
        ),
    )


def notify_line_chat_staff_message(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    body_text: str,
    author_label: str,
    author_user_id: uuid.UUID,
) -> list[Notification]:
    """Inbox alerts for customers on the line when staff posts in chat."""
    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(col(QueueEntry.user_id).is_not(None))
    ).all()
    preview = body_text.strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."
    message_body = f"{author_label}: {preview}"
    fired: list[Notification] = []
    for ticket in rows:
        if ticket.user_id is None or ticket.user_id == author_user_id:
            continue
        user = session.get(User, ticket.user_id)
        if user is None or not user.is_active:
            continue
        result = dispatch(
            session,
            user=user,
            payload=NotificationPayload(
                kind=NotificationKind.line_chat_update,
                body=message_body,
                ticket_id=ticket.id,
                service_item_id=service_item_id,
            ),
        )
        if result is not None:
            fired.append(result)
    return fired


def count_unread_notifications(session: Session, *, user: User) -> int:
    raw = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id)
        .where(col(Notification.read_at).is_(None))
    ).one()
    return int(raw[0] if isinstance(raw, tuple) else raw)


def _ticket_position(session: Session, ticket: QueueEntry) -> int:
    """Queue depth for alert thresholds, in Call Next order.

    These alerts say "you're next" and "start heading over", so they only
    mean anything if they track the ticket the counter is actually about
    to serve. Anchoring them to ticket numbers instead — the old
    behaviour, defended as "stable" — sent "you're next" to whoever held
    the lowest number while Call Next served a VIP issued minutes later,
    and the person walking to the counter was the wrong one.

    Parked spots are skipped for the same reason: Call Next passes over
    them, so they do not stand between anybody and the counter. See
    :mod:`werefa.queue.application.line_order`.
    """
    from werefa.queue.application import line_order

    return line_order.callable_position(session, ticket)


def evaluate_smart_alerts_for_service_line(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> list[Notification]:
    """Walk every active ticket on a service line and dispatch the
    appropriate alert (if any).

    Designed to run *after* the queue mutation has committed: each call
    is idempotent thanks to ``last_alert_position`` and safe to invoke
    even when nothing changed.
    """
    from werefa.queue.application import line_order, liveness_service
    from werefa.realtime.notify import notify_queue_subscribers

    liveness_touched = liveness_service.sync_liveness_for_service_line(
        session, service_item_id
    )

    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(col(QueueEntry.user_id).is_not(None))
        .order_by(*line_order.call_order())
    ).all()

    has_serving_ahead = any(
        t.status == TicketStatus.serving.value for t in rows
    )

    fired: list[Notification] = []
    for ticket in rows:
        if ticket.status == TicketStatus.serving.value:
            continue
        if line_order.is_held(ticket):
            # Their spot is parked: Call Next is deliberately passing over
            # them, so "you're next — head to the counter now" would be a
            # lie, and telling a parked customer to hurry contradicts the
            # hold notification they just got. ``last_alert_position`` is
            # left untouched so the real alert still fires once the park
            # ends.
            continue
        pos = _ticket_position(session, ticket)
        if pos < 1:
            continue
        decision = decide_alert(
            position=pos,
            last_alert_position=ticket.last_alert_position,
            top_k=settings.LIVENESS_TOP_K,
            has_serving_ahead=has_serving_ahead,
        )
        if decision is None:
            continue
        if ticket.user_id is None:
            continue  # walk-ins skipped (no registered recipient)
        user = session.get(User, ticket.user_id)
        if user is None or not user.is_active:
            continue
        result = dispatch(
            session,
            user=user,
            payload=NotificationPayload(
                kind=decision.kind,
                body=decision.body,
                ticket_id=ticket.id,
                service_item_id=service_item_id,
                position=pos,
            ),
        )
        if result is not None:
            fired.append(result)
        ticket.last_alert_position = pos
        session.add(ticket)

    should_commit = (
        bool(fired)
        or liveness_touched
        or any(t.last_alert_position is not None for t in rows)
    )
    if should_commit:
        # Commit so subsequent reads see the fresh ledger rows + alerts
        # state without leaking the open transaction across requests.
        session.commit()

    if liveness_touched:
        notify_queue_subscribers(session, service_item_id, reason="liveness")

    return fired


def run_evaluate_smart_alerts_for_service_line(service_item_id: uuid.UUID) -> None:
    """Background-task entry point: opens its own DB session.

    Never pass the request-scoped ``Session`` into ``BackgroundTasks`` — it is
    closed when the HTTP response finishes, which leaves pooled connections in
    a bad state and surfaces as intermittent 500s on position pings.
    """
    try:
        from sqlmodel import Session

        with Session(engine) as session:
            evaluate_smart_alerts_for_service_line(
                session, service_item_id=service_item_id
            )
    except Exception:
        logger.exception(
            "Smart alerts failed after position ping",
            extra={"service_item_id": str(service_item_id)},
        )


def mark_notification_read(
    session: Session, *, user: User, notification_id: uuid.UUID
) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    row.read_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_user_notifications(
    session: Session, *, user: User, limit: int, offset: int
) -> tuple[list[Notification], int]:
    # MED-3: COUNT(*) instead of materialising every row — the new
    # ``(user_id, created_at)`` index makes both reads a single index
    # scan.
    total_raw = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id)
    ).one()
    total = int(total_raw[0] if isinstance(total_raw, tuple) else total_raw)
    page = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(col(Notification.created_at).desc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(page).all()
    return list(rows), total


def update_prefs(
    session: Session, *, user: User, body: NotificationPrefsUpdate
) -> User:
    valid = {c.value for c in NotificationChannel}
    bad = [v for v in body.notification_prefs if v not in valid]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown notification channel(s): {bad}",
        )
    # Preserve order from the request; that's the user's preference.
    user.notification_prefs = list(body.notification_prefs)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def reset_prefs_default() -> list[str]:
    return list(settings.NOTIFICATION_DEFAULT_PREFS)


# Convenience re-export for hook sites that don't want to import the
# enum themselves.
__all__ = [
    "NotificationChannel",
    "NotificationKind",
    "EMAIL_COPY_KINDS",
    "REMOTE_CHANNELS",
    "PromptDelivery",
    "alert_reach",
    "count_unread_notifications",
    "deliver_job",
    "delivery_fallbacks",
    "dispatch",
    "record_delivery_receipt",
    "get_delivery_queue",
    "submit_delivery_job",
    "set_delivery_queue",
    "set_delivery_session_factory",
    "evaluate_smart_alerts_for_service_line",
    "notify_line_chat_staff_message",
    "notify_ticket_now_serving",
    "notify_ticket_staff_you_are_next",
    "STAFF_YOU_ARE_NEXT_BODY",
    "run_evaluate_smart_alerts_for_service_line",
    "get_registry",
    "list_user_notifications",
    "mark_notification_read",
    "reset_prefs_default",
    "set_registry",
    "update_prefs",
]
