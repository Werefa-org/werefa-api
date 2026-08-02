"""The service row is the queue mutex — every order-changing write must take it.

``call_next`` has always locked the ``ServiceItem`` row before reading the
tickets it decides from. That only serialises anything if the *other*
writers take the same lock, because ``SELECT ... FOR UPDATE`` on a row
excludes nothing but another locker of that row.

The path that motivated this: staff bump a VIP while a colleague clicks
Call Next. Call Next locks the service row, reads the order, and sees the
ordinary customer at the front. The bump — taking no lock at all — commits
straight past it. Call Next then commits, having served the customer it
read before the bump landed. The VIP was promoted and immediately passed
over, and the data afterwards showed nothing unusual: no conflict, no
error, just a queue that had ignored an instruction.

So the property under test is not "the right ticket is served" for one
lucky interleaving — it is that these writes *cannot* interleave at all.
Each one is run against a held mutex and must wait for it.
"""

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlmodel import Session

from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.core.db import engine
from werefa.identity.infrastructure import repo as identity_repo
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application import liveness_service
from werefa.queue.application import service as queue_service
from werefa.service_items.infrastructure import repo as service_item_repo
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    ProviderCreate,
    ServiceItemCreate,
    User,
    UserCreate,
)

#: How long to let a mutation run against a held mutex before concluding it
#: is genuinely blocked. A mutation that ignores the lock finishes in
#: single-digit milliseconds, so this is orders of magnitude of headroom
#: while keeping the module quick.
BLOCK_PROBE_SECONDS = 1.0

#: Ceiling for the same mutation once the mutex is released.
COMPLETION_TIMEOUT_SECONDS = 10.0


def _line_with_two_waiting_tickets(
    db: Session,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An ordinary customer at the front, a would-be VIP behind them.

    Returns ids rather than instances: each ticket is created in its own
    session (one active ticket per user is enforced per connection), so the
    ORM objects are detached by the time the caller sees them.
    """
    owner = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert owner is not None
    provider = provider_repo.create_provider(
        session=db,
        body=ProviderCreate(
            slug=f"mutex-{uuid.uuid4().hex[:8]}",
            biz_name="Mutex provider",
            owner_user_id=owner.id,
        ),
    )
    service_item = service_item_repo.create_service_item(
        session=db,
        provider_id=provider.id,
        body=ServiceItemCreate(
            name="Service",
            avg_duration_minutes=15,
            price=Decimal("10.00"),
        ),
    )

    ticket_ids: list[uuid.UUID] = []
    for _ in range(2):
        user = identity_repo.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(), password=random_lower_string()[:12]
            ),
        )
        with Session(engine) as session:
            joined = session.get(User, user.id)
            assert joined is not None
            ticket = queue_service.join_queue_remote(
                session,
                service_item_id=service_item.id,
                user=joined,
                access_code=None,
            )
            ticket_ids.append(ticket.id)
    first_id, second_id = ticket_ids
    return service_item.id, first_id, second_id


def _run_against_held_mutex(
    service_item_id: uuid.UUID,
    mutation: Callable[[Session], None],
) -> tuple[bool, bool]:
    """Run *mutation* while another transaction holds the line's mutex.

    Returns ``(finished_while_held, finished_after_release)``. A write that
    respects the mutex yields ``(False, True)``; one that ignores it yields
    ``(True, True)``.
    """
    mutex_held = threading.Event()
    release_mutex = threading.Event()
    mutation_done = threading.Event()
    failures: list[BaseException] = []

    def _hold_mutex() -> None:
        try:
            with Session(engine) as session:
                queue_service.get_service_for_update(session, service_item_id)
                mutex_held.set()
                release_mutex.wait(COMPLETION_TIMEOUT_SECONDS)
                session.commit()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            failures.append(exc)
            mutex_held.set()

    def _run_mutation() -> None:
        try:
            with Session(engine) as session:
                mutation(session)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            failures.append(exc)
        finally:
            mutation_done.set()

    holder = threading.Thread(target=_hold_mutex, name="mutex-holder")
    holder.start()
    assert mutex_held.wait(COMPLETION_TIMEOUT_SECONDS), "mutex never acquired"

    runner = threading.Thread(target=_run_mutation, name="mutation")
    runner.start()
    finished_while_held = mutation_done.wait(BLOCK_PROBE_SECONDS)

    release_mutex.set()
    finished_after_release = mutation_done.wait(COMPLETION_TIMEOUT_SECONDS)

    holder.join(COMPLETION_TIMEOUT_SECONDS)
    runner.join(COMPLETION_TIMEOUT_SECONDS)
    if failures:
        raise failures[0]
    return finished_while_held, finished_after_release


MutationBuilder = Callable[[uuid.UUID, uuid.UUID, uuid.UUID], Callable[[Session], None]]


def _mutations() -> dict[str, MutationBuilder]:
    """Every write that can change who Call Next will serve next."""

    def priority_bump(
        sid: uuid.UUID, _first: uuid.UUID, second: uuid.UUID
    ) -> Callable[[Session], None]:
        return lambda session: queue_service.set_ticket_priority(
            session, service_item_id=sid, ticket_id=second, priority=1
        )

    def terminal_status(
        sid: uuid.UUID, first: uuid.UUID, _second: uuid.UUID
    ) -> Callable[[Session], None]:
        return lambda session: queue_service.set_ticket_status(
            session,
            ticket_id=first,
            service_item_id=sid,
            new_status=TicketStatus.cancelled,
        )

    def hold(
        sid: uuid.UUID, first: uuid.UUID, _second: uuid.UUID
    ) -> Callable[[Session], None]:
        return lambda session: liveness_service.hold_ticket(
            session, ticket_id=first, service_item_id=sid
        )

    def release(
        sid: uuid.UUID, first: uuid.UUID, _second: uuid.UUID
    ) -> Callable[[Session], None]:
        return lambda session: liveness_service.release_hold(
            session, ticket_id=first, service_item_id=sid
        )

    def call_next(
        sid: uuid.UUID, _first: uuid.UUID, _second: uuid.UUID
    ) -> Callable[[Session], None]:
        return lambda session: queue_service.call_next_transition(session, sid)

    return {
        "priority_bump": priority_bump,
        "terminal_status": terminal_status,
        "hold": hold,
        "release_hold": release,
        # Control: this one always took the mutex. If it ever reports
        # "finished while held", the probe itself is broken and the other
        # cases in this module prove nothing.
        "call_next": call_next,
    }


@pytest.mark.parametrize("mutation_name", sorted(_mutations()))
def test_order_changing_writes_wait_for_the_queue_mutex(
    db: Session, mutation_name: str
) -> None:
    service_item_id, first_id, second_id = _line_with_two_waiting_tickets(db)
    build = _mutations()[mutation_name]

    finished_while_held, finished_after_release = _run_against_held_mutex(
        service_item_id, build(service_item_id, first_id, second_id)
    )

    assert not finished_while_held, (
        f"{mutation_name} committed while another transaction held the "
        "line's queue mutex, so it can interleave with Call Next between "
        "the read that picks a ticket and the write that serves it"
    )
    assert finished_after_release, (
        f"{mutation_name} never completed after the mutex was released"
    )


def test_a_vip_bump_that_commits_first_is_the_ticket_call_next_serves(
    db: Session,
) -> None:
    """The semantics the lock exists to protect, checked end to end."""
    service_item_id, ordinary_id, vip_id = _line_with_two_waiting_tickets(db)

    with Session(engine) as session:
        queue_service.set_ticket_priority(
            session,
            service_item_id=service_item_id,
            ticket_id=vip_id,
            priority=1,
        )

    with Session(engine) as session:
        _current, served = queue_service.call_next_transition(
            session, service_item_id
        )
        assert served is not None
        served_id = served.id

    assert served_id == vip_id, (
        "the VIP was bumped to the front and Call Next served the ordinary "
        "customer anyway"
    )
    assert served_id != ordinary_id


def test_concurrent_call_next_never_serves_a_ticket_twice(db: Session) -> None:
    """Several staff clicking Call Next at once still walk the line once.

    The mutex is what makes this true; without a serialising lock two
    callers can read the same "next" ticket and both move it to serving,
    which is the double-call staff described under load.
    """
    owner = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert owner is not None
    provider = provider_repo.create_provider(
        session=db,
        body=ProviderCreate(
            slug=f"mutex-{uuid.uuid4().hex[:8]}",
            biz_name="Mutex provider",
            owner_user_id=owner.id,
        ),
    )
    service_item = service_item_repo.create_service_item(
        session=db,
        provider_id=provider.id,
        body=ServiceItemCreate(
            name="Service", avg_duration_minutes=15, price=Decimal("10.00")
        ),
    )

    ticket_count = 6
    for _ in range(ticket_count):
        user = identity_repo.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(), password=random_lower_string()[:12]
            ),
        )
        with Session(engine) as session:
            joined = session.get(User, user.id)
            assert joined is not None
            queue_service.join_queue_remote(
                session,
                service_item_id=service_item.id,
                user=joined,
                access_code=None,
            )

    barrier = threading.Barrier(ticket_count)

    def _call_next(_index: int) -> uuid.UUID | None:
        barrier.wait(COMPLETION_TIMEOUT_SECONDS)
        with Session(engine) as session:
            _current, served = queue_service.call_next_transition(
                session, service_item.id
            )
            return served.id if served is not None else None

    with ThreadPoolExecutor(max_workers=ticket_count) as pool:
        served_ids = list(pool.map(_call_next, range(ticket_count)))

    called = [tid for tid in served_ids if tid is not None]
    assert len(called) == ticket_count, (
        f"expected every ticket to be called once, got {len(called)}"
    )
    assert len(set(called)) == ticket_count, (
        "the same ticket was served by more than one concurrent Call Next"
    )
