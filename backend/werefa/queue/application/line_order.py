"""One definition of "who gets called next" for a service line.

Four modules used to answer "where is this ticket in the line", and no
two of them agreed:

* Call Next ordered by ``(priority desc, joined_at)`` and skipped parked
  spots;
* the liveness top-K window used ``(priority desc, joined_at)`` but
  ignored holds;
* the FR-07 smart alerts counted **ticket numbers**, so a VIP issued late
  was invisible to them; and
* the realtime payload counted ticket numbers too.

The visible damage was a customer being told "you're next" while Call
Next was about to serve somebody else, and the person genuinely about to
be called never being asked to check in. So the ordering lives here once,
and everything else imports it.

Two questions are answered separately, because they are different
questions and conflating them is what produced the drift:

:func:`line_position`
    "You are #N in line." Counts everyone ahead **plus** whoever is at
    the counter, and ignores holds — a parked ticket has not lost its
    place, so it still occupies one. This is the number customers and
    staff boards read.

:func:`callable_position`
    "N calls away from being served." Mirrors :func:`next_callable`
    exactly: parked spots are passed over, so they do not count as ahead
    of anybody. This is the number anything that must agree with Call
    Next has to use — the liveness watch window and the alert
    thresholds.

They differ only while a hold is live, which is precisely the window in
which the old code went wrong.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import Session, col, select

from werefa.shared.enums import TicketStatus
from werefa.shared.models import QueueEntry, utcnow

#: Statuses that occupy a place in the line.
ACTIVE_STATUSES = (TicketStatus.waiting.value, TicketStatus.serving.value)

#: Sort fallback for a ticket that has not been persisted yet. The column
#: is never null in practice — the database stamps it on insert — so this
#: only keeps the in-Python key total.
_UNJOINED = datetime(1970, 1, 1, tzinfo=timezone.utc)


def call_order() -> tuple[Any, ...]:
    """SQL ``ORDER BY`` for the sequence tickets are called in."""
    return (col(QueueEntry.priority).desc(), col(QueueEntry.joined_at))


def call_order_key(ticket: QueueEntry) -> tuple[int, datetime]:
    """In-Python sort key matching :func:`call_order`."""
    return (-(ticket.priority or 0), ticket.joined_at or _UNJOINED)


def is_held(ticket: QueueEntry, *, now: datetime | None = None) -> bool:
    """Is this spot parked right now? (FR-05 hold.)"""
    now = now or utcnow()
    return (
        ticket.liveness_hold_until is not None
        and now < ticket.liveness_hold_until
    )


def _ahead_of(ticket: QueueEntry) -> ColumnElement[bool]:
    """Rows that come before *ticket*, including *ticket* itself.

    A ``serving`` ticket always counts as ahead: somebody at the counter
    is unambiguously in front of everyone still waiting, whatever their
    priority or join time.
    """
    return or_(
        col(QueueEntry.status) == TicketStatus.serving.value,
        col(QueueEntry.priority) > ticket.priority,
        (col(QueueEntry.priority) == ticket.priority)
        & (col(QueueEntry.joined_at) <= ticket.joined_at),
    )


def _count(session: Session, statement: Any) -> int:
    raw = session.exec(statement).one()
    if isinstance(raw, tuple):
        raw = raw[0]
    return int(raw or 0)


def line_position(session: Session, ticket: QueueEntry) -> int:
    """1-based place in line, counting whoever is at the counter.

    Held tickets keep their place here — a hold parks a spot, it does not
    give it away — so this is the number to show a customer or a staff
    board. Use :func:`callable_position` for anything that has to predict
    Call Next.
    """
    statement = (
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.service_item_id == ticket.service_item_id)
        .where(col(QueueEntry.status).in_(ACTIVE_STATUSES))
        .where(_ahead_of(ticket))
    )
    return _count(session, statement)


def callable_position(
    session: Session, ticket: QueueEntry, *, now: datetime | None = None
) -> int:
    """1-based place in the order Call Next will actually use.

    Parked spots are skipped by :func:`next_callable`, so they are not
    counted as ahead of anyone. For a ticket that is itself parked this
    reports where it would land if the hold ended now, which is the
    honest answer to "how far are they from the counter" — but callers
    driving customer-facing alerts should check :func:`is_held` first and
    stay quiet, because Call Next is not about to serve them.
    """
    now = now or utcnow()
    statement = (
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.service_item_id == ticket.service_item_id)
        .where(col(QueueEntry.status).in_(ACTIVE_STATUSES))
        .where(_ahead_of(ticket))
        .where(
            or_(
                col(QueueEntry.id) == ticket.id,
                col(QueueEntry.liveness_hold_until).is_(None),
                col(QueueEntry.liveness_hold_until) <= now,
            )
        )
    )
    return _count(session, statement)


def next_callable(
    session: Session,
    service_item_id: uuid.UUID,
    *,
    now: datetime | None = None,
    for_update: bool = False,
) -> QueueEntry | None:
    """First waiting ticket whose spot is not currently parked (FR-05).

    A held ticket keeps its place in the ordering — it is simply passed
    over until the customer checks in, staff release it, or the timer runs
    out. That is the whole point: the line keeps moving without anybody
    losing their turn.

    If *every* waiting ticket is held we call the first one anyway. A
    hold is a courtesy, and a courtesy that can idle a counter with
    customers still in the line has stopped being one.

    Pass ``for_update=True`` only from the path that is about to *claim*
    the returned ticket (Call Next). It row-locks the candidate so the row
    cannot change between the read that chose it and the write that serves
    it. The prediction callers — the liveness watch window, the FR-07
    alert thresholds — must leave it ``False``: they are read-only and
    have no business taking write locks on a customer's row.
    """
    now = now or utcnow()
    base = (
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.waiting.value)
        .order_by(*call_order())
    )
    if for_update:
        base = base.with_for_update()
    callable_now = session.exec(
        base.where(
            or_(
                col(QueueEntry.liveness_hold_until).is_(None),
                col(QueueEntry.liveness_hold_until) <= now,
            )
        )
    ).first()
    if callable_now is not None:
        return callable_now
    return session.exec(base).first()


__all__ = [
    "ACTIVE_STATUSES",
    "call_order",
    "call_order_key",
    "callable_position",
    "is_held",
    "line_position",
    "next_callable",
]
