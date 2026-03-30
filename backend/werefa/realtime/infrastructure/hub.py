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

    async def local_publish(self, service_item_id: uuid.UUID, message: str) -> None:
        async with self._lock:
            subs = list(self._subscribers.get(service_item_id, ()))
        for q in subs:
            await q.put(message)
