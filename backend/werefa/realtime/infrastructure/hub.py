import asyncio
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable

TypeUnsub = Callable[[], Awaitable[None]]


class InMemoryQueueHub:
    """
    Fan-out to local WebSocket subscribers for one service_item_id channel.
    Thread-safe: publish should be scheduled on the app asyncio loop.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._subscribers: dict[uuid.UUID, list[asyncio.Queue[str]]] = defaultdict(
            list
        )

    async def subscribe(
        self, service_item_id: uuid.UUID
    ) -> tuple[asyncio.Queue[str], TypeUnsub]:
        q: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self._subscribers[service_item_id].append(q)

        async def _unsub() -> None:
            async with self._lock:
                try:
                    self._subscribers[service_item_id].remove(q)
                except ValueError:
                    pass

        return q, _unsub

    async def subscriber_snapshot(self) -> tuple[int, dict[str, int]]:
        async with self._lock:
            by_line = {str(k): len(v) for k, v in self._subscribers.items()}
            total = sum(len(v) for v in self._subscribers.values())
        return total, by_line

    async def local_publish(self, service_item_id: uuid.UUID, message: str) -> int:
        """Fan out, and report how many subscriber queues took the message.

        The count is the honest answer to "did this reach anyone?", which
        the notification dispatcher needs and a bare success cannot give
        it: publishing to a line nobody is watching succeeds completely
        and delivers to nobody.
        """
        async with self._lock:
            subs = list(self._subscribers.get(service_item_id, ()))
        for q in subs:
            await q.put(message)
        return len(subs)

    def local_publish_nowait(
        self, service_item_id: uuid.UUID, message: str
    ) -> int:
        """Same fan-out as :meth:`local_publish`, completed synchronously.

        Must be called **on the event loop thread**. It exists for callers
        that have to know the publish finished before they return and cannot
        await — specifically the notification dispatcher, whose result
        decides whether SMS and email get tried. Scheduling a task and
        claiming success there books an alert as delivered that may never
        have gone out.

        Nothing here can block: the queues are unbounded, so ``put_nowait``
        always succeeds, and the snapshot is a plain list copy. The
        ``_lock`` is deliberately not taken — acquiring it is the only await
        in :meth:`local_publish`, and taking it would reintroduce exactly
        the suspension this method exists to avoid. That is safe because
        this never awaits, so no other coroutine can interleave with it, and
        ``_subscribers`` is only ever mutated from the loop thread by
        :meth:`subscribe` and its unsubscribe.
        """
        subs = list(self._subscribers.get(service_item_id, ()))
        for q in subs:
            q.put_nowait(message)
        return len(subs)
