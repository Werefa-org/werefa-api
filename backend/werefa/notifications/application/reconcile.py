"""Sweep up notification rows the delivery worker never resolved (FR-07).

The worker keeps jobs in memory, which the ledger already admits to: a row
is written ``queued`` at dispatch and only the worker ever writes the final
``delivered``/``failed``. Kill the process in between — a crash, an OOM, a
deploy that drops what is still queued on the way down — and the row stays
``queued`` with nobody left who knows about it. Until now nothing went back
for those, so "we owed this customer a text and never sent it" was a state
the database recorded and no code ever read.

This module reads it. On boot (see ``werefa.main``) it walks the abandoned
rows and gives each one an ending: back to the worker if the message still
holds, ``failed`` otherwise. Which of the two is a *policy* question and
lives in :mod:`werefa.notifications.domain.reconcile`, deliberately away
from the SQL — the short version is that a re-send needs both a message
still worth delivering *and* proof it was never delivered the first time,
and most rows have neither.

That proof is ``Notification.delivery_attempts``, which the worker writes
before it calls a provider rather than after. Without it, a row killed
between "the gateway accepted this" and "the ledger says delivered" is
indistinguishable from one that never left the queue, and reconciling the
two the same way texts somebody twice.

Still in process, still no broker. The retry path is the same
:class:`~werefa.notifications.infrastructure.delivery.DeliveryQueue` that
dispatch feeds, so a reconciled send gets the same backoff, the same
channel fall-through and the same overload shedding as a fresh one.

Two things this cannot reach, both by design:

* The **email copy** of a queue-critical alert owns no ledger row
  (``EMAIL_COPY_KINDS``), so a lost copy leaves no trace to reconcile. The
  primary channel's row is the one that matters and it is covered.
* Rows younger than ``NOTIFICATION_RECONCILE_MIN_AGE_SECONDS``, which are
  probably in flight *right now* — this process is not guaranteed to be
  the only one, and during a rolling deploy it certainly is not.

And one thing this deliberately does *not* touch: a row reading ``sent``.
That is not a zombie. The gateway accepted the message and owes us a
delivery receipt (``werefa.notifications.domain.receipts``); there is no
job left in anybody's memory to resume, and the message is on a carrier's
network whatever we do next. A row that stays ``sent`` means the receipt
never came, which is an honest record of not knowing — re-sending it
would text somebody twice for the sake of tidying a status column.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.core.db import engine
from werefa.notifications.application import service
from werefa.notifications.domain.reconcile import ZombieAction, decide_reconcile
from werefa.notifications.infrastructure.delivery import DeliveryJob
from werefa.notifications.notifier import NotificationPayload
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from werefa.shared.models import Notification, QueueEntry, User, utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconcileReport:
    """Outcome of one sweep. Returned for logs and tests, not for callers
    to act on — by the time this exists every row has been dealt with."""

    scanned: int = 0
    requeued: int = 0
    failed: int = 0
    unconfirmed: int = 0
    """Subset of ``failed`` that had already reached a gateway. These are
    the ones we resolved rather than re-sent, so a non-zero count means
    somebody may have been notified without the ledger being able to say
    so — and that the process is dying mid-send often enough to notice."""

    left_in_flight: int = 0
    """Rows the policy judged too young to touch. Normally zero: the query
    pre-filters on the same threshold."""

    truncated: bool = False
    """The batch cap was hit, so more zombies remain for the next sweep."""


def reconcile_stuck_notifications(
    *,
    session: Session | None = None,
    now: datetime | None = None,
) -> ReconcileReport:
    """Resolve every abandoned ``queued`` row, retrying what is still true.

    Synchronous, and it talks to both the database and (indirectly) the
    delivery queue — so it must not be called from the event loop. The
    lifespan hook runs it on a worker thread.

    ``session`` and ``now`` are injection points for tests; in production
    this opens its own session, because the only caller is startup and
    there is no request session to borrow.
    """
    if session is not None:
        return _sweep(session, now=now or utcnow())
    with Session(engine) as owned:
        return _sweep(owned, now=now or utcnow())


def _sweep(session: Session, *, now: datetime) -> ReconcileReport:
    min_age = settings.NOTIFICATION_RECONCILE_MIN_AGE_SECONDS
    max_age = settings.NOTIFICATION_RECONCILE_MAX_AGE_SECONDS
    limit = settings.NOTIFICATION_RECONCILE_MAX_ROWS

    rows = _abandoned_rows(
        session, before=now - timedelta(seconds=min_age), limit=limit
    )

    jobs: list[DeliveryJob] = []
    requeued = 0
    failed = 0
    left = 0
    unconfirmed = 0

    for row in rows:
        kind = _kind_of(row.kind)
        age = _age_seconds(row.created_at, now)
        action = decide_reconcile(
            kind=kind,
            age_seconds=age,
            delivery_attempts=row.delivery_attempts,
            min_age_seconds=min_age,
            max_age_seconds=max_age,
        )

        if action is ZombieAction.leave:
            left += 1
            continue

        job: DeliveryJob | None = None
        if action is ZombieAction.retry:
            job = _job_for(
                session, row, kind=kind, channel=_channel_of(row.channel)
            )

        if job is None:
            # Either the policy said so, or the retry turned out to be
            # unbuildable — an unreadable channel, a user who has since
            # been deactivated. Both end the same way: the row stops
            # lying about being in progress.
            row.status = NotificationStatus.failed.value
            session.add(row)
            failed += 1
            if row.delivery_attempts > 0:
                unconfirmed += 1
                # Operationally distinct from the rest: this one reached a
                # gateway and we never heard back, so ``failed`` is the
                # safe reading rather than a known one. Worth its own line
                # in the logs, because a run of these means the process is
                # dying mid-send.
                logger.error(
                    "notification_reconcile_unconfirmed_delivery",
                    extra={
                        "notification_id": str(row.id),
                        "channel": row.channel,
                        "kind": row.kind,
                        "delivery_attempts": row.delivery_attempts,
                    },
                )
                continue
            logger.warning(
                "notification_reconcile_marked_failed",
                extra={
                    "notification_id": str(row.id),
                    "channel": row.channel,
                    "kind": row.kind,
                    "age_seconds": None if age is None else round(age, 1),
                },
            )
            continue

        jobs.append(job)
        requeued += 1

    # Commit before submitting: the worker re-reads these rows in a session
    # of its own, so nothing may still be sitting in ours when it starts.
    if failed:
        session.commit()
    for job in jobs:
        service.submit_delivery_job(job)
        logger.info(
            "notification_reconcile_requeued",
            extra={
                "notification_id": str(job.notification_id),
                "channel": job.channel.value,
                "kind": job.payload.kind.value,
            },
        )

    report = ReconcileReport(
        scanned=len(rows),
        requeued=requeued,
        failed=failed,
        unconfirmed=unconfirmed,
        left_in_flight=left,
        truncated=len(rows) >= limit,
    )
    if report.scanned:
        logger.warning(
            "notification_reconcile_found_stuck_rows",
            extra={
                "scanned": report.scanned,
                "requeued": report.requeued,
                "failed": report.failed,
                "unconfirmed": report.unconfirmed,
                "truncated": report.truncated,
            },
        )
    else:
        logger.info("notification_reconcile_clean")
    return report


def _abandoned_rows(
    session: Session, *, before: datetime, limit: int
) -> list[Notification]:
    """Candidate zombies, oldest first.

    The age filter here is a pre-filter for the database's benefit, not
    the rule — :func:`decide_reconcile` is the authority and re-checks it.
    A ``NULL`` ``created_at`` is pulled in deliberately: an age we cannot
    measure is not an age we can call safe, and the policy resolves those
    without sending.
    """
    stmt = (
        select(Notification)
        .where(Notification.status == NotificationStatus.queued.value)
        .where(
            or_(
                col(Notification.created_at) <= before,
                col(Notification.created_at).is_(None),
            )
        )
        .order_by(col(Notification.created_at))
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def _job_for(
    session: Session,
    row: Notification,
    *,
    kind: NotificationKind | None,
    channel: NotificationChannel | None,
) -> DeliveryJob | None:
    """Rebuild the job dispatch handed over, or ``None`` if we cannot.

    The ledger keeps everything a remote send needs except
    ``service_item_id``, which is re-read from the ticket — a fall-through
    to the websocket channel is a no-op without it.
    """
    if kind is None or channel is None:
        return None
    if channel not in service.REMOTE_CHANNELS:
        # ``queued`` is only ever written for a channel that leaves the
        # box, so this is corrupt data rather than a state to resume.
        logger.error(
            "notification_reconcile_unexpected_channel",
            extra={"notification_id": str(row.id), "channel": row.channel},
        )
        return None
    if not settings.NOTIFICATION_DELIVERY_ASYNC:
        # The rollback lever is off, which means "no off-request sends".
        # Resolving the row is still right; re-queueing it would not be.
        return None

    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    payload = NotificationPayload(
        kind=kind,
        body=row.body,
        ticket_id=row.ticket_id,
        service_item_id=_service_item_of(session, row.ticket_id),
        position=row.position,
        # The alert is about the moment it was raised, not about now.
        occurred_at=row.created_at,
    ).with_default_time()

    return DeliveryJob(
        user_id=user.id,
        channel=channel,
        payload=payload,
        notification_id=row.id,
        fallback_channels=service.delivery_fallbacks(
            user, channel=channel, kind=kind
        ),
    )


def _service_item_of(
    session: Session, ticket_id: uuid.UUID | None
) -> uuid.UUID | None:
    if ticket_id is None:
        return None
    ticket = session.get(QueueEntry, ticket_id)
    return None if ticket is None else ticket.service_item_id


def _age_seconds(created_at: datetime | None, now: datetime) -> float | None:
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        # Defensive: the column is ``timezone=True``, but a row written by
        # an older build (or a stub in a test) may not carry one, and
        # subtracting a naive from an aware datetime raises.
        created_at = created_at.replace(tzinfo=now.tzinfo)
    return (now - created_at).total_seconds()


# The ledger's ``kind`` and ``channel`` are plain ``varchar`` columns, so a
# value this build does not know about — a rollback to an older image, a
# hand-edited row — must resolve to ``None`` rather than crash the sweep.


def _kind_of(raw: str) -> NotificationKind | None:
    try:
        return NotificationKind(raw)
    except ValueError:
        return None


def _channel_of(raw: str) -> NotificationChannel | None:
    try:
        return NotificationChannel(raw)
    except ValueError:
        return None


__all__ = ["ReconcileReport", "reconcile_stuck_notifications"]
