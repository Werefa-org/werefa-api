"""The one ordering everything else has to agree with.

Call Next, the FR-05 liveness watch window, the FR-07 alerts, the queue
snapshot and the realtime payload each used to answer "where is this
ticket" on their own, and they disagreed the moment a VIP joined or a
spot was parked. The observable damage: "you're next" reaching a customer
the counter was not about to serve, and a held spot being called anyway.

So the two questions are pinned down here, side by side, because the only
thing that keeps them honest is that they are different on purpose:
:func:`line_position` is "you are #N in line" and a park keeps its place;
:func:`callable_position` is "N calls from the counter" and a park is
passed over, exactly like :func:`next_callable` does it.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlmodel import Session

from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application import line_order
from werefa.queue.application import service as queue_service
from werefa.service_items.infrastructure import repo as service_item_repo
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    ProviderCreate,
    QueueEntry,
    ServiceItemCreate,
    utcnow,
)


def _line(db: Session) -> uuid.UUID:
    owner = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert owner is not None
    provider = provider_repo.create_provider(
        session=db,
        body=ProviderCreate(
            slug=f"order-{uuid.uuid4().hex[:8]}",
            biz_name="Ordering provider",
            owner_user_id=owner.id,
        ),
    )
    item = service_item_repo.create_service_item(
        session=db,
        provider_id=provider.id,
        body=ServiceItemCreate(
            name="Counter",
            avg_duration_minutes=10,
            price=Decimal("1.00"),
        ),
    )
    return item.id


def _walk_in(db: Session, sid: uuid.UUID, name: str, *, vip: bool = False):
    return queue_service.join_queue_walk_in(
        db, service_item_id=sid, guest_name=name, is_vip=vip
    )


def _park(db: Session, ticket: QueueEntry, *, seconds: int = 300) -> None:
    ticket.liveness_hold_until = utcnow() + timedelta(seconds=seconds)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)


def test_call_order_key_puts_vips_first_then_arrival(db: Session) -> None:
    sid = _line(db)
    early = _walk_in(db, sid, "early")
    late_vip = _walk_in(db, sid, "late vip", vip=True)
    later = _walk_in(db, sid, "later")

    ordered = sorted([early, later, late_vip], key=line_order.call_order_key)
    assert [t.id for t in ordered] == [late_vip.id, early.id, later.id]


def test_a_vip_is_ahead_of_an_earlier_ticket_number(db: Session) -> None:
    sid = _line(db)
    early = _walk_in(db, sid, "early")
    late_vip = _walk_in(db, sid, "late vip", vip=True)

    assert line_order.line_position(db, late_vip) == 1
    assert line_order.line_position(db, early) == 2
    assert line_order.next_callable(db, sid).id == late_vip.id


def test_whoever_is_at_the_counter_counts_as_ahead(db: Session) -> None:
    sid = _line(db)
    first = _walk_in(db, sid, "first")
    second = _walk_in(db, sid, "second")

    _, serving = queue_service.call_next_transition(db, sid)
    assert serving is not None and serving.id == first.id

    db.refresh(second)
    assert line_order.line_position(db, second) == 2


def test_a_park_keeps_its_place_in_line_but_not_in_the_call_order(
    db: Session,
) -> None:
    """The distinction the whole module exists for.

    A parked customer has not lost their turn — they are still #1 in the
    line, and that is what a board or a snapshot should say. They are
    simply not the next person the counter will call, and anything
    predicting Call Next has to know that.
    """
    sid = _line(db)
    parked = _walk_in(db, sid, "parked")
    behind = _walk_in(db, sid, "behind")
    _park(db, parked)

    assert line_order.line_position(db, parked) == 1
    assert line_order.line_position(db, behind) == 2

    assert line_order.callable_position(db, behind) == 1
    assert line_order.next_callable(db, sid).id == behind.id


def test_an_expired_park_is_callable_again(db: Session) -> None:
    sid = _line(db)
    parked = _walk_in(db, sid, "parked")
    _walk_in(db, sid, "behind")
    _park(db, parked, seconds=-1)

    assert line_order.callable_position(db, parked) == 1
    assert line_order.next_callable(db, sid).id == parked.id


def test_a_fully_parked_line_still_calls_somebody(db: Session) -> None:
    """A courtesy that can idle a counter has stopped being one."""
    sid = _line(db)
    first = _walk_in(db, sid, "first")
    second = _walk_in(db, sid, "second")
    _park(db, first)
    _park(db, second)

    assert line_order.next_callable(db, sid).id == first.id


def test_terminal_tickets_leave_the_line(db: Session) -> None:
    sid = _line(db)
    gone = _walk_in(db, sid, "gone")
    still_here = _walk_in(db, sid, "still here")

    queue_service.set_ticket_status(
        db, gone.id, sid, TicketStatus.cancelled
    )

    db.refresh(still_here)
    assert line_order.line_position(db, still_here) == 1
    assert line_order.next_callable(db, sid).id == still_here.id
