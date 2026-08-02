"""Harness for exercising the realtime hand-off from a non-loop thread.

The bug class these support is specific: scheduling work onto the app's
event loop from a worker thread in a way that does not *wake* the loop. It
only shows up when the loop has nothing else to do, so the loop here is
deliberately idle — ``run_forever`` with nothing scheduled parks in
``select()`` with no timeout, which is what a queue backend does between
requests. Do not "simplify" that idleness away; it is the test condition.
"""

import asyncio
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

#: Generous next to the delivery we expect (sub-millisecond) and still fast
#: enough that a regression fails the suite promptly rather than hanging it.
DELIVERY_TIMEOUT_SECONDS = 3.0


class RecordingCoordinator:
    """Stands in for ``RealtimeCoordinator``; records what reached the loop.

    ``can_publish_now`` mirrors the real coordinator's two deployments: it
    is ``True`` when there is no Redis hop (the publish is pure in-process
    bookkeeping and can finish synchronously) and ``False`` when there is
    one (a network round trip that needs the loop).

    ``recipients`` is the subscriber count a publish reports back. It
    defaults to 1 — somebody was listening — because these tests are
    about the hand-off reaching the loop, not about the audience. A test
    that cares passes ``0`` (provably nobody) or ``None`` (unknowable,
    the Redis fan-out), which are the two the dispatcher treats
    differently.
    """

    def __init__(
        self, *, can_publish_now: bool = True, recipients: int | None = 1
    ) -> None:
        self.published: list[tuple[uuid.UUID, str]] = []
        self.arrived = threading.Event()
        self.can_publish_now = can_publish_now
        self.recipients = recipients

    async def publish(
        self, service_item_id: uuid.UUID, message: str
    ) -> int | None:
        self._record(service_item_id, message)
        return self.recipients

    def try_publish_now(
        self, service_item_id: uuid.UUID, message: str
    ) -> int | None:
        if not self.can_publish_now:
            return None
        self._record(service_item_id, message)
        return self.recipients

    def _record(self, service_item_id: uuid.UUID, message: str) -> None:
        self.published.append((service_item_id, message))
        self.arrived.set()


class HangingCoordinator:
    """A coordinator whose publish never completes (wedged Redis)."""

    def __init__(self) -> None:
        self.started = threading.Event()

    async def publish(self, service_item_id: uuid.UUID, message: str) -> None:
        self.started.set()
        await asyncio.Event().wait()

    def try_publish_now(
        self, service_item_id: uuid.UUID, message: str
    ) -> int | None:
        return None


@contextmanager
def idle_event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A real event loop on its own thread with nothing whatsoever to do."""
    loop = asyncio.new_event_loop()
    running = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(running.set)
        loop.run_forever()

    thread = threading.Thread(target=_run, name="idle-loop", daemon=True)
    thread.start()
    assert running.wait(5.0), "test loop never started"
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5.0)
        loop.close()
