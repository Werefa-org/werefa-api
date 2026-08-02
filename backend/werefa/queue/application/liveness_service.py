"""FR-05 / Phase 11: top-K liveness sync, check-ins, and spot holds.

The original flow ended at ``flagged``: one missed grace window turned the
badge red and that was the last thing the system had to say. Staff were
left to call the customer anyway, which produced a ``serving`` ticket, a
no-show, and a strike — so in practice the only consequence of a flag was
making a penalty *more* likely for the person it was meant to protect.

This module keeps the observation but adds the missing next step, under
three rules:

* **Confirmation, not GPS — and not background traffic either.** Only a
  deliberate check-in clears a grace window, and it clears one with or
  without coordinates, so a failed GPS read costs nobody their spot. App
  polling is recorded as evidence (:func:`touch_activity`) and given no
  power over the state machine: an app left open at home would otherwise
  make a real absentee permanently unflaggable.
* **Two strikes on the window, not one.** The first missed window sends a
  warning and re-arms; only consecutive misses flag. See
  ``LIVENESS_MISSES_BEFORE_FLAG``.
* **The next step is a hold, not a punishment.** :func:`hold_ticket` parks
  the spot so the line moves on, keeps the ticket ``waiting``, and tells
  the customer their place is safe until a stated time. Holds are capped;
  once spent, staff call the customer like anyone else.

  A park is a question, not a sentence: it lasts exactly as long as the
  silence that caused it. A check-in answers that question, so it
  **unparks the spot immediately** (:func:`record_position_ping`) and the
  customer is callable again with their place untouched — no waiting out
  a timer that has lost its reason. Staff can also unpark early with
  :func:`release_hold`, and the timer ends it if nobody does. What must
  *not* end it is the line moving: a VIP join or other tickets being
  served leaves the park exactly where it was, because the customer was
  given a time and Call Next has to honour it until something real
  changes.

* **Silence only counts if they were asked.** Every rule above reads a
  missing check-in as an answer, which it is not when the prompt never
  arrived. The notification ledger now distinguishes "the carrier
  delivered it" from "the carrier rejected it" from "we do not know"
  (:mod:`werefa.notifications.domain.receipts`), and a window whose
  prompt provably failed re-arms without costing a miss and without
  flagging — see :attr:`WindowOutcome.unreachable`. It also stops
  re-sending down the channel that just failed, and hands the customer to
  staff through :func:`liveness_rules.recommend` instead.

  The commonest case is not a carrier at all. ``logger`` is the
  always-succeeds backstop appended to every preference list, so a
  customer with no reachable channel produces a ledger full of
  ``delivered`` rows and was, before this, flagged for ignoring prompts
  that were never sent anywhere.

The third rule is what makes the first one safe to enforce strictly: a
flag costs the customer a held spot and a loud notification, never a
penalty, so there is no need to soften the evidence bar to protect them.

Nothing here can set a terminal status or record a strike. The only route
to a strike remains ``set_ticket_status(no_show)`` after a human called
the customer.

Known limit, unchanged from before: a coordinate carries no proof of
proximity — we never compare it to the provider's location — so a
check-in means "I am still with you", not "I am nearby". Treating it as
the latter is what the hold flow deliberately avoids.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.notifications.notifier import NotificationPayload
from werefa.queue.application import line_order
from werefa.queue.application import service as queue_service
from werefa.queue.domain import liveness_rules
from werefa.queue.domain.liveness_rules import (
    LivenessSnapshot,
    Recommendation,
    WindowOutcome,
)
from werefa.shared.enums import (
    LivenessAction,
    LivenessState,
    NotificationKind,
    NotificationReach,
    TicketSource,
    TicketStatus,
)
from werefa.shared.models import PositionPing, QueueEntry, User, utcnow

if TYPE_CHECKING:
    # Import-time only. The notification service imports this module
    # back (lazily, inside its functions), so a runtime import here
    # would close the cycle.
    from werefa.notifications.application.service import PromptDelivery

logger = logging.getLogger(__name__)

REMOTE_SOURCES = (TicketSource.remote_app.value, TicketSource.qr_scan.value)

PROMPT_KINDS: frozenset[NotificationKind] = frozenset(
    {
        NotificationKind.liveness_ping_request,
        NotificationKind.liveness_stale,
        NotificationKind.liveness_hold,
    }
)
"""The alerts whose silence this module reads as an answer.

All three ask the customer for the same thing — open the ticket and tap
"I'm on my way" — so all three are prompts whose non-arrival excuses the
non-answer. ``liveness_hold`` is in the list for the least obvious reason
of the three: a hold sets the grace deadline to the end of the park, so
an undelivered hold notification would otherwise expire into a miss for a
customer who was never told their spot was being held at all.

Deliberately not every kind. "You're next" and "now serving" are
statements, not questions, and losing one is a different problem from the
one being solved here.
"""


def _reach_for(
    session: Session, ticket_ids: list[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, PromptDelivery]:
    """Did the last prompt reach each of these tickets?

    Values carry the reach plus the ledger evidence behind it. The
    notification service is imported inside the call for the same reason
    :func:`_notify` does it: it reaches back into this module, and
    neither should need the other at import time.

    ``now`` is passed rather than left to the notification service's own
    clock so that "has this receipt gone unanswered too long?" and "has
    this grace window expired?" are decided at the same instant. Two
    clocks would let a caller reasoning about one moment read row ages
    from another — which is exactly what a time-travelling test does, and
    a difference that would silently only show up there.
    """
    from werefa.notifications.application import service as notifications_service

    return notifications_service.alert_reach(
        session, ticket_ids=ticket_ids, kinds=PROMPT_KINDS, now=now
    )


def _reach(
    delivery_map: dict[uuid.UUID, PromptDelivery], ticket_id: uuid.UUID
) -> NotificationReach:
    """Reach for one ticket, defaulting to "nothing was asked"."""
    entry = delivery_map.get(ticket_id)
    return NotificationReach.unconfirmed if entry is None else entry.reach


def _is_remote(ticket: QueueEntry) -> bool:
    return ticket.source in REMOTE_SOURCES


def _watched(session: Session, ticket: QueueEntry, *, now: datetime) -> bool:
    """Is this ticket close enough to the counter for us to ask?

    Two ways in, and the second is not optional:

    * its **callable** position is inside top-K — the order Call Next
      will actually use, so the people about to be called are the ones we
      ask. Counting the line naively meant a parked spot ahead of them
      pushed the person we were genuinely about to serve out of the
      window; counting ticket numbers (the older bug) did the same to
      anyone behind a late VIP.
    * it is currently held. A parked spot is by definition one we are
      waiting on, so it stays watched — and stays on the board — however
      far the line has moved since.
    """
    if not _is_remote(ticket) or ticket.status != TicketStatus.waiting.value:
        return False
    if line_order.is_held(ticket, now=now):
        return True
    position = line_order.callable_position(session, ticket, now=now)
    return position <= settings.LIVENESS_TOP_K


def _snapshot(
    ticket: QueueEntry,
    *,
    now: datetime,
    watched: bool,
    last_ping_at: datetime | None = None,
    warning_reach: NotificationReach = NotificationReach.unconfirmed,
) -> LivenessSnapshot:
    return LivenessSnapshot(
        state=ticket.liveness_state,
        now=now,
        deadline_at=ticket.liveness_deadline_at,
        last_ping_at=last_ping_at,
        last_seen_at=ticket.liveness_last_seen_at,
        misses=ticket.liveness_misses,
        hold_until=ticket.liveness_hold_until,
        hold_count=ticket.liveness_hold_count,
        in_top_k=watched,
        warning_reach=warning_reach,
    )


def recommend_for(
    session: Session,
    ticket: QueueEntry,
    *,
    now: datetime | None = None,
    watched: bool | None = None,
    last_ping_at: datetime | None = None,
    warning_reach: NotificationReach | None = None,
) -> Recommendation:
    """Staff-facing next step for one ticket.

    ``warning_reach`` is looked up when not supplied. Callers walking a
    whole line pass it in from one batched read instead — see
    :func:`build_liveness_board`.
    """
    now = now or utcnow()
    if watched is None:
        watched = _watched(session, ticket, now=now)
    if warning_reach is None:
        warning_reach = _reach(
            _reach_for(session, [ticket.id], now=now), ticket.id
        )
    return liveness_rules.recommend(
        _snapshot(
            ticket,
            now=now,
            watched=watched,
            last_ping_at=last_ping_at,
            warning_reach=warning_reach,
        ),
        activity_grace_seconds=settings.LIVENESS_ACTIVITY_GRACE_SECONDS,
        max_holds=settings.LIVENESS_MAX_HOLDS,
    )


def _last_ping(session: Session, ticket_id: uuid.UUID) -> PositionPing | None:
    return session.exec(
        select(PositionPing)
        .where(PositionPing.ticket_id == ticket_id)
        .order_by(col(PositionPing.sent_at).desc())
    ).first()


def _reset_to_idle(
    ticket: QueueEntry, *, now: datetime, drop_hold: bool
) -> bool:
    """Stop tracking a ticket. Returns whether anything changed.

    Used when a ticket leaves the watch window. The grace-window
    bookkeeping goes — we are no longer asking this customer anything —
    but a *live* hold does not, unless ``drop_hold`` says the ticket has
    left the line entirely (called, cancelled, completed), where a park
    is meaningless.

    Dropping a live hold here is what used to make a VIP join look like
    it deleted the park: the ticket fell out of top-K, the hold silently
    vanished, and Call Next went straight back to the customer staff had
    just told "your spot is held for the next 10 minutes". A hold ends
    when the customer checks in, when staff release it, or when its timer
    runs out — never as a side effect of the line moving.
    """
    expired_hold = (
        ticket.liveness_hold_until is not None
        and now >= ticket.liveness_hold_until
    )
    clearing_hold = ticket.liveness_hold_until is not None and (
        drop_hold or expired_hold
    )
    if (
        ticket.liveness_state == LivenessState.idle.value
        and ticket.liveness_deadline_at is None
        and ticket.liveness_misses == 0
        and not clearing_hold
    ):
        return False
    ticket.liveness_state = LivenessState.idle.value
    ticket.liveness_deadline_at = None
    ticket.liveness_misses = 0
    if clearing_hold:
        ticket.liveness_hold_until = None
    return True


def _notify(
    session: Session,
    ticket: QueueEntry,
    *,
    kind: NotificationKind,
    body: str,
    position: int | None = None,
) -> None:
    from werefa.notifications.application import service as notifications_service

    if ticket.user_id is None:
        return
    user = session.get(User, ticket.user_id)
    if user is None:
        return
    notifications_service.dispatch(
        session,
        user=user,
        payload=NotificationPayload(
            kind=kind,
            body=body,
            ticket_id=ticket.id,
            service_item_id=ticket.service_item_id,
            position=position,
        ),
    )


def sync_liveness_for_service_line(
    session: Session, service_item_id: uuid.UUID
) -> bool:
    """Advance liveness states for remote waiting tickets in top-K.

    Returns ``True`` when any row or ledger mutation occurred so callers
    know to commit.

    A ticket whose prompt provably never arrived is parked rather than
    left to be found: see :func:`_auto_hold`, which runs once at the end
    so the whole line's decisions are made before the queue mutex is
    taken.
    """
    if not settings.LIVENESS_ENABLED:
        return False
    now = utcnow()
    dirty = False
    unreachable: list[uuid.UUID] = []
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

    # One read for the line, before anything below dispatches: what we are
    # asking about is the prompt that opened the window now expiring, not
    # one this sweep is about to send.
    reach = _reach_for(session, [t.id for t in rows], now=now)

    for ticket in rows:
        # Being called ends the question: they are at the counter or they
        # are not, and that is a human judgement from here on. A park on a
        # ticket that has left the line means nothing, so it goes too.
        if ticket.status != TicketStatus.waiting.value:
            if _reset_to_idle(ticket, now=now, drop_hold=True):
                session.add(ticket)
                dirty = True
            continue

        if not _is_remote(ticket):
            continue

        if not _watched(session, ticket, now=now):
            # Outside the watch window we stop asking — but a live hold
            # survives, because staff promised the customer a time and
            # Call Next reads that column. ``_reset_to_idle`` still clears
            # a hold that has run out.
            if _reset_to_idle(ticket, now=now, drop_hold=False):
                session.add(ticket)
                dirty = True
            continue

        # An expired hold simply makes the ticket callable again; the
        # ledger of how often it was held survives in ``hold_count``.
        if (
            ticket.liveness_hold_until is not None
            and now >= ticket.liveness_hold_until
        ):
            ticket.liveness_hold_until = None
            session.add(ticket)
            dirty = True

        # Notification copy says "you are #N in line", so it is the plain
        # line position, holds included — not the Call Next ordering the
        # window above is gated on.
        pos = line_order.line_position(session, ticket)

        if ticket.liveness_state == LivenessState.idle.value:
            ticket.liveness_state = LivenessState.awaiting.value
            ticket.liveness_deadline_at = now + timedelta(
                seconds=settings.LIVENESS_GRACE_SECONDS
            )
            ticket.liveness_misses = 0
            session.add(ticket)
            _notify(
                session,
                ticket,
                kind=NotificationKind.liveness_ping_request,
                body=(
                    "You're near the front of the line — tap to confirm "
                    "you're on the way. Sharing your location is optional."
                ),
                position=pos,
            )
            dirty = True
            continue

        if ticket.liveness_state not in (
            LivenessState.awaiting.value,
            LivenessState.ok.value,
        ):
            # ``flagged`` rests until contact resumes: re-flagging every
            # poll would just spam the customer we already failed to reach.
            continue

        outcome = liveness_rules.classify_window(
            _snapshot(
                ticket,
                now=now,
                watched=True,
                warning_reach=_reach(reach, ticket.id),
            ),
            misses_before_flag=settings.LIVENESS_MISSES_BEFORE_FLAG,
        )
        if outcome == WindowOutcome.within_window:
            continue

        if outcome == WindowOutcome.unreachable:
            # The prompt never got to them, so the expired window is our
            # news, not theirs. Re-arm it — the next attempt may land, and
            # a customer whose deadline is left in the past would be
            # re-judged on every poll — but score no miss and do not flag.
            #
            # And do *not* send another one. The ledger says the dispatcher
            # already exhausted every channel this customer has; repeating
            # the same message down the same dead path each window is noise
            # with a gateway bill attached.
            #
            # Parking the spot is the part that matters, and it happens
            # below rather than here: it needs the queue mutex, and taking
            # that mid-loop would mean deciding the line's order from reads
            # made before the lock.
            ticket.liveness_deadline_at = now + timedelta(
                seconds=settings.LIVENESS_GRACE_SECONDS
            )
            session.add(ticket)
            unreachable.append(ticket.id)
            logger.warning(
                "liveness_prompt_undelivered",
                extra={
                    "ticket_id": str(ticket.id),
                    "service_item_id": str(service_item_id),
                    "liveness_state": ticket.liveness_state,
                    "misses": ticket.liveness_misses,
                    # The evidence, not just the verdict. A run of
                    # ``sms``/``sent`` here is a status-callback URL that
                    # never resolved — which from the board looks exactly
                    # like a line full of unreachable customers.
                    "prompt_channel": getattr(
                        getattr(reach.get(ticket.id), "channel", None),
                        "value",
                        None,
                    ),
                    "prompt_status": getattr(
                        getattr(reach.get(ticket.id), "status", None),
                        "value",
                        None,
                    ),
                },
            )
            dirty = True
            continue

        ticket.liveness_misses += 1
        if outcome == WindowOutcome.warn:
            ticket.liveness_deadline_at = now + timedelta(
                seconds=settings.LIVENESS_GRACE_SECONDS
            )
            session.add(ticket)
            _notify(
                session,
                ticket,
                kind=NotificationKind.liveness_stale,
                body=(
                    "We haven't heard from you and you're near the front. "
                    "Open your ticket and tap 'I'm on my way' to keep your spot."
                ),
                position=pos,
            )
            dirty = True
            continue

        ticket.liveness_state = LivenessState.flagged.value
        session.add(ticket)
        _notify(
            session,
            ticket,
            kind=NotificationKind.liveness_stale,
            body=(
                "We still haven't heard from you. Staff may hold your spot "
                "and serve the next customer — open your ticket to confirm "
                "you're on the way."
            ),
            position=pos,
        )
        dirty = True

    # Last, and once for the whole line: parking takes the queue mutex, so
    # it must not happen inside a loop that is still deciding.
    if _auto_hold(session, service_item_id, unreachable, now=now):
        dirty = True

    return dirty


def _auto_hold(
    session: Session,
    service_item_id: uuid.UUID,
    candidates: list[uuid.UUID],
    *,
    now: datetime,
) -> bool:
    """Park the spots we could not get a message to. Returns "anything changed?".

    Why this exists: without it, "we could not reach them" was a line on
    the staff board and nothing else. The line's *next* move was Call
    Next reaching the head of the queue anyway, nobody answering, and a
    no-show recorded against a customer who was never spoken to — the
    exact outcome this module was written to prevent, arrived at from a
    new direction. A hold costs them nothing, keeps their place, and lets
    the line move; it is the answer the module already had.

    Two things make this safe to do from inside the sync loop.

    **It takes the queue mutex before it decides.** A park changes who
    Call Next skips, so it is an order-changing write like any other
    (:func:`queue_service.get_service_for_update`). The loop above read
    its tickets *without* the lock — those reads are about liveness
    timers and the notification ledger, neither of which the mutex
    protects — so every ticket is re-read under the lock here and
    re-validated before anything is written. Postgres row locks are
    reentrant within a transaction, so a caller already holding it pays
    nothing, and there is only ever this one lock, so no ordering
    hazard exists.

    **It does not commit.** :func:`hold_ticket` does, because staff hold
    one ticket and that is the whole request; this runs inside somebody
    else's transaction, where committing would settle work that is not
    ours to settle. The lock is therefore held until the caller commits,
    which is precisely how long the mutex is supposed to be held.

    The hold notification will usually fail to arrive too — the channel
    that could not carry the prompt cannot carry this either. That is
    fine and deliberate: it lands on the logger backstop, keeps the
    ticket's reach reading ``not_reached``, and the customer's place is
    protected whether or not they ever hear about it.
    """
    if not candidates or not settings.LIVENESS_AUTO_HOLD_UNREACHABLE:
        return False

    queue_service.get_service_for_update(session, service_item_id)

    changed = False
    for ticket_id in candidates:
        ticket = session.get(QueueEntry, ticket_id)
        if ticket is None:
            continue
        # The identity map may still be holding what we read before the
        # lock; the whole point of taking it is to decide on what is true
        # now.
        session.refresh(ticket)
        if (
            ticket.service_item_id != service_item_id
            or ticket.status != TicketStatus.waiting.value
            or not _is_remote(ticket)
        ):
            continue
        if line_order.is_held(ticket, now=now):
            # Someone got there first — staff, or an earlier pass.
            continue
        if ticket.liveness_state == LivenessState.ok.value:
            # They checked in between the loop's read and this lock. A
            # check-in is the answer the prompt was asking for, so there
            # is nothing left to park them over.
            continue
        if ticket.liveness_hold_count >= settings.LIVENESS_MAX_HOLDS:
            # Holds are spent. The line cannot keep stepping over one
            # ticket forever, so from here it really is a human's call —
            # ``recommend`` says so, and only a human can end it.
            logger.warning(
                "liveness_unreachable_holds_exhausted",
                extra={
                    "ticket_id": str(ticket.id),
                    "service_item_id": str(service_item_id),
                    "hold_count": ticket.liveness_hold_count,
                },
            )
            continue

        _apply_hold(session, ticket, seconds=None, now=now)
        logger.warning(
            "liveness_auto_held_unreachable",
            extra={
                "ticket_id": str(ticket.id),
                "service_item_id": str(service_item_id),
                "hold_count": ticket.liveness_hold_count,
            },
        )
        changed = True
    return changed


def touch_activity(session: Session, ticket: QueueEntry) -> None:
    """Record a background poll from the ticket holder's app.

    Evidence only. It stamps ``liveness_last_seen_at`` so staff can see
    "their app is online but silent", and does nothing else: it does not
    reset the miss counter, re-arm the deadline, or change the state.

    That restraint is the point. An app polling in the background says a
    process is running on a phone somewhere — not that anyone read the
    prompt. Letting it clear a window would make a customer who left the
    app open at home permanently unflaggable, which is precisely the
    no-show we most need staff to see coming.
    """
    ticket.liveness_last_seen_at = utcnow()
    session.add(ticket)


def record_position_ping(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    user: User,
    latitude: float | None,
    longitude: float | None,
    accuracy_m: int | None,
) -> QueueEntry:
    """Customer check-in, with or without coordinates.

    A coordinate-free check-in is a first-class citizen: it clears the miss
    counter and returns the ticket to ``ok``. The only thing it does not do
    is write a :class:`PositionPing` row, so staff can still tell
    "confirmed with location" from "confirmed without".

    **A check-in ends an active hold immediately.** The park exists for
    one reason — we could not reach this customer — so the moment they
    answer, its reason is gone and they are callable again with their
    place intact. That is what the hold notification promises them in so
    many words ("tap 'I'm on my way' — you keep your place"), and making
    them sit out the rest of a timer they no longer need is the same
    punishment the hold model exists to avoid.

    The "a phone in a pocket could cancel the park" worry is answered one
    layer up, not here: background polling goes to :func:`touch_activity`
    and moves nothing. Only a deliberate tap reaches this function, and a
    deliberate tap is exactly the evidence the hold was waiting for.

    ``liveness_hold_count`` is *not* refunded. The park was spent the
    moment it was granted, so a customer cannot check in, go quiet again,
    and collect an unlimited supply of fresh holds.
    """
    # A check-in clears the park outright and makes the spot callable
    # again immediately, so it is an order change and takes the mutex.
    queue_service.get_service_for_update(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if (
        ticket is None
        or ticket.service_item_id != service_item_id
        or ticket.user_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != TicketStatus.waiting.value:
        raise HTTPException(
            status_code=400,
            detail="Check-ins are only accepted for waiting tickets",
        )
    if not _is_remote(ticket):
        raise HTTPException(
            status_code=400,
            detail="Walk-in tickets do not use remote liveness check-ins",
        )

    now = utcnow()
    if latitude is not None and longitude is not None:
        session.add(
            PositionPing(
                ticket_id=ticket.id,
                latitude=latitude,
                longitude=longitude,
                accuracy_m=accuracy_m,
            )
        )

    # Unpark them. ``hold_count`` stays where it is: the hold is spent,
    # not refunded.
    ticket.liveness_hold_until = None
    ticket.liveness_state = LivenessState.ok.value
    ticket.liveness_deadline_at = now + timedelta(
        seconds=settings.LIVENESS_GRACE_SECONDS
    )
    ticket.liveness_last_seen_at = now
    ticket.liveness_misses = 0
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def hold_ticket(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    hold_seconds: int | None = None,
) -> QueueEntry:
    """Park a spot: the line calls past this ticket for a bounded window.

    This is the counter-side action the flag was always implying. The
    ticket stays ``waiting`` the whole time — no terminal status, no
    strike, no reordering — so a customer stuck in a lift loses minutes,
    not their place.
    """
    # A park changes who Call Next skips, so it takes the line's queue
    # mutex like every other order-changing write. Without it, Call Next
    # could read the order, this hold could land, and Call Next could then
    # serve the ticket that was just parked.
    queue_service.get_service_for_update(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != TicketStatus.waiting.value:
        raise HTTPException(
            status_code=409,
            detail="Only waiting tickets can be held",
        )
    if not _is_remote(ticket):
        raise HTTPException(
            status_code=400,
            detail="Walk-in tickets are already at the counter",
        )
    if ticket.liveness_hold_count >= settings.LIVENESS_MAX_HOLDS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This ticket has already been held "
                f"{ticket.liveness_hold_count} time(s). Call the customer "
                "and use no-show if they do not appear."
            ),
        )

    _apply_hold(session, ticket, seconds=hold_seconds, now=utcnow())
    session.commit()
    session.refresh(ticket)
    return ticket


def _apply_hold(
    session: Session,
    ticket: QueueEntry,
    *,
    seconds: int | None,
    now: datetime,
) -> None:
    """Park one spot and tell the customer. Shared, and does not commit.

    Split out of :func:`hold_ticket` so the automatic hold
    (:func:`_auto_hold`) parks a spot in exactly the same way a member of
    staff does — same window arithmetic, same reset, same wording to the
    customer. A second implementation would be a second set of rules
    about somebody's place in a queue, which is the class of drift
    :mod:`werefa.queue.application.line_order` exists to have ended.

    Committing is the caller's job: staff hold one ticket and commit;
    the sync loop parks what it found and lets its own dirty-tracking
    decide.
    """
    seconds = seconds or settings.LIVENESS_HOLD_SECONDS
    ticket.liveness_hold_until = now + timedelta(seconds=seconds)
    ticket.liveness_hold_count += 1
    # A hold buys the customer a fresh chance, so the grace window restarts
    # and the miss counter goes back to zero. Otherwise the hold we granted
    # would itself push them straight back to ``flagged``.
    ticket.liveness_state = LivenessState.awaiting.value
    ticket.liveness_deadline_at = ticket.liveness_hold_until
    ticket.liveness_misses = 0
    session.add(ticket)

    minutes = max(1, seconds // 60)
    _notify(
        session,
        ticket,
        kind=NotificationKind.liveness_hold,
        body=(
            f"We couldn't reach you, so we're serving the next customer "
            f"while your spot is held for {minutes} more minute(s). "
            "Open your ticket and tap 'I'm on my way' — you keep your place."
        ),
        position=line_order.line_position(session, ticket),
    )


def release_hold(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
) -> QueueEntry:
    """Staff saw the customer arrive (or changed their mind): unpark."""
    # Unparking makes the ticket callable again — an order change, so it
    # takes the queue mutex.
    queue_service.get_service_for_update(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.liveness_hold_until is not None:
        ticket.liveness_hold_until = None
        # The grace window ran to the end of the park, so an early release
        # leaves it already spent. Re-arm it rather than letting the next
        # sync score a miss the customer never had a chance to answer —
        # they were parked on our say-so, and a release usually means staff
        # can see them. ``liveness_misses`` is left alone (an unpark is not
        # an amnesty), and a customer who did check in keeps their ``ok``.
        now = utcnow()
        if ticket.status == TicketStatus.waiting.value and (
            ticket.liveness_deadline_at is None
            or ticket.liveness_deadline_at <= now
        ):
            ticket.liveness_deadline_at = now + timedelta(
                seconds=settings.LIVENESS_GRACE_SECONDS
            )
            if ticket.liveness_state != LivenessState.ok.value:
                ticket.liveness_state = LivenessState.awaiting.value
        # The hold is spent either way; releasing early must not hand out a
        # free extra hold, or a customer could be shuffled indefinitely.
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
    return ticket


def read_liveness(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    seen_by_owner: bool = False,
) -> tuple[QueueEntry, PositionPing | None, Recommendation]:
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if seen_by_owner and ticket.status == TicketStatus.waiting.value:
        # Order matters: stamp activity *before* the sync so a customer
        # watching their own ticket cannot be flagged by the very poll that
        # proves they are paying attention.
        touch_activity(session, ticket)
        session.commit()

    touched = sync_liveness_for_service_line(session, ticket.service_item_id)
    if touched:
        session.commit()
    session.refresh(ticket)

    last = _last_ping(session, ticket_id)
    rec = recommend_for(
        session, ticket, last_ping_at=last.sent_at if last else None
    )
    return ticket, last, rec


def build_liveness_board(
    session: Session, service_item_id: uuid.UUID
) -> list[dict[str, object]]:
    """Top-K liveness for one line, each row carrying its next step.

    This is the view staff actually work from: everyone close enough to be
    called, what we know about them, and what to do about it. Held tickets
    are included even if the line has moved them out of the top-K window —
    a parked spot must never fall off the board unseen. That is the same
    :func:`_watched` rule the sync loop uses, so the board shows exactly
    the tickets the system is still asking about.

    ``position`` is the plain line position ("they are #3"), while
    membership follows the Call Next ordering — see
    :mod:`werefa.queue.application.line_order` for why those differ.
    """
    touched = sync_liveness_for_service_line(session, service_item_id)
    if touched:
        session.commit()

    now = utcnow()
    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.waiting.value)
        .where(col(QueueEntry.user_id).is_not(None))
        .order_by(*line_order.call_order())
    ).all()

    reach = _reach_for(session, [t.id for t in rows], now=now)

    board: list[dict[str, object]] = []
    for ticket in rows:
        if not _watched(session, ticket, now=now):
            continue
        pos = line_order.line_position(session, ticket)
        last = _last_ping(session, ticket.id)
        ticket_reach = _reach(reach, ticket.id)
        rec = liveness_rules.recommend(
            _snapshot(
                ticket,
                now=now,
                watched=True,
                last_ping_at=last.sent_at if last else None,
                warning_reach=ticket_reach,
            ),
            activity_grace_seconds=settings.LIVENESS_ACTIVITY_GRACE_SECONDS,
            max_holds=settings.LIVENESS_MAX_HOLDS,
        )
        user = session.get(User, ticket.user_id) if ticket.user_id else None
        board.append(
            {
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "position": pos,
                "user_full_name": user.full_name if user else None,
                "user_phone": user.phone_number if user else None,
                "liveness_state": ticket.liveness_state,
                "liveness_deadline_at": ticket.liveness_deadline_at,
                "last_ping_at": last.sent_at if last else None,
                "last_seen_at": ticket.liveness_last_seen_at,
                "misses": ticket.liveness_misses,
                "hold_until": ticket.liveness_hold_until,
                "hold_count": ticket.liveness_hold_count,
                # Staff-visible answer to "have they even been told?", so
                # a red badge can never be read as "they ignored us"
                # without the board saying whether we got through.
                "warning_reach": ticket_reach.value,
                "recommended_action": rec.action.value,
                "recommended_reason": rec.reason,
                "can_hold": rec.can_hold
                and ticket.liveness_hold_count < settings.LIVENESS_MAX_HOLDS,
            }
        )
    return board


__all__ = [
    "LivenessAction",
    "build_liveness_board",
    "hold_ticket",
    "read_liveness",
    "recommend_for",
    "record_position_ping",
    "release_hold",
    "sync_liveness_for_service_line",
    "touch_activity",
]
