"""How a fan-out gets from a request thread onto the app event loop.

Almost every endpoint that mutates the queue is a sync ``def`` route, so it
runs in Starlette's worker threadpool and *not* on the loop the WebSockets
live on. Getting that hand-off wrong does not raise and does not lose the
event outright — it strands it — which is why it surfaced as "sometimes the
board just doesn't update" rather than as a traceable failure.

These tests pin the hand-off itself. The loop they run against is
deliberately idle: ``run_forever`` with nothing scheduled parks in
``select()`` with no timeout, which is exactly the state a queue backend
sits in between requests, and exactly the state that made the bug visible.
"""

import asyncio
import threading
import time
import uuid
from collections.abc import Iterator
from typing import cast

import pytest
from sqlmodel import Session

from tests.utils.realtime import (
    DELIVERY_TIMEOUT_SECONDS,
    RecordingCoordinator,
    idle_event_loop,
)
from werefa.realtime import lifespan
from werefa.realtime.notify import notify_queue_subscribers


@pytest.fixture
def realtime_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[asyncio.AbstractEventLoop, RecordingCoordinator]]:
    coordinator = RecordingCoordinator()
    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        yield loop, coordinator


def test_queue_event_from_a_worker_thread_reaches_an_idle_loop(
    realtime_loop: tuple[asyncio.AbstractEventLoop, RecordingCoordinator],
) -> None:
    """The regression: a sync route's event must wake the loop, not wait for it.

    ``loop.create_task`` is not thread-safe. Called from a worker thread it
    appends the task to the loop's ready queue without writing the loop's
    self-pipe, so an idle loop stays blocked in ``select()`` and the publish
    runs only when some unrelated traffic happens to wake it. Nothing is
    logged and nothing raises; the event simply arrives late by an unbounded
    amount, or — if the line goes quiet — not before the customer gives up.

    This test runs on pytest's own thread, which is not the loop thread, so
    it exercises exactly the hand-off every Call Next and hold performs.
    """
    _loop, coordinator = realtime_loop
    service_item_id = uuid.uuid4()

    notify_queue_subscribers(
        cast(Session, None), service_item_id, reason="call_next"
    )

    assert coordinator.arrived.wait(DELIVERY_TIMEOUT_SECONDS), (
        "fan-out never ran: the event was scheduled on the loop but the loop "
        "was never woken to run it"
    )
    assert len(coordinator.published) == 1
    published_id, payload = coordinator.published[0]
    assert published_id == service_item_id
    assert '"reason":"call_next"' in payload.replace(" ", "")


def test_every_event_in_a_burst_is_scheduled(
    realtime_loop: tuple[asyncio.AbstractEventLoop, RecordingCoordinator],
) -> None:
    """Several staff acting at once must not cost anybody their event.

    The reported symptom was worst under concurrency, so the burst is driven
    from several threads rather than one.
    """
    _loop, coordinator = realtime_loop
    service_item_id = uuid.uuid4()
    reasons = [f"call_next_{i}" for i in range(20)]
    barrier = threading.Barrier(len(reasons))

    def _fire(reason: str) -> None:
        barrier.wait(5.0)
        notify_queue_subscribers(
            cast(Session, None), service_item_id, reason=reason
        )

    threads = [
        threading.Thread(target=_fire, args=(reason,)) for reason in reasons
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)

    # Bounded: a regression here strands events, so this must not wait for
    # a count that will never arrive.
    give_up_at = time.monotonic() + DELIVERY_TIMEOUT_SECONDS
    while (
        len(coordinator.published) < len(reasons)
        and time.monotonic() < give_up_at
    ):
        time.sleep(0.02)

    seen = {
        payload.replace(" ", "").split('"reason":"')[1].split('"')[0]
        for _sid, payload in coordinator.published
    }
    assert seen == set(reasons), f"missing: {set(reasons) - seen}"


def test_event_scheduled_from_the_loop_thread_still_works(
    realtime_loop: tuple[asyncio.AbstractEventLoop, RecordingCoordinator],
) -> None:
    """The one async caller (join-with-files) is already on the loop.

    That path must keep using ``create_task`` — going through the
    thread-safe route from the loop thread is legal but pointless, and the
    branch that decides between them needs a test on both sides.
    """
    loop, coordinator = realtime_loop
    service_item_id = uuid.uuid4()

    async def _notify_from_the_loop() -> None:
        notify_queue_subscribers(
            cast(Session, None), service_item_id, reason="join"
        )

    asyncio.run_coroutine_threadsafe(_notify_from_the_loop(), loop).result(5.0)

    assert coordinator.arrived.wait(DELIVERY_TIMEOUT_SECONDS)
    assert coordinator.published[0][0] == service_item_id


def test_fan_out_is_dropped_quietly_once_the_loop_has_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown must not turn a queue mutation into a 500.

    The realtime stack is best-effort: the row is already committed and the
    REST endpoints still serve it, so a fan-out that has nowhere to go is
    dropped rather than raised.
    """
    coordinator = RecordingCoordinator()
    loop = asyncio.new_event_loop()
    loop.close()
    monkeypatch.setattr(lifespan, "coordinator", coordinator)
    monkeypatch.setattr(lifespan, "main_event_loop", loop)

    notify_queue_subscribers(cast(Session, None), uuid.uuid4(), reason="join")

    assert coordinator.published == []
