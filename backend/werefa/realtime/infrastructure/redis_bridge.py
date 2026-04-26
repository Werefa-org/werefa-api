import asyncio
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis

from werefa.realtime.infrastructure.hub import InMemoryQueueHub

logger = logging.getLogger(__name__)


def _channel(sid: uuid.UUID) -> str:
    return f"werefa:queue:{sid}"


class RedisPubSubBackend:
    """
    Connect workers: each process psubscribes to `werefa:queue:*` and fan-outs to
    `InMemoryQueueHub`. Publishes go only to Redis; local hub is driven by the listener.
    """

    def __init__(self, url: str, hub: InMemoryQueueHub) -> None:
        self._url = url
        self._hub = hub
        self._client: Any = None
        self._pub: Any = None
        self._sub_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
            self._url, decode_responses=True
        )
        assert self._client is not None
        self._pub = self._client.pubsub(ignore_subscribe_messages=True)
        await self._pub.psubscribe("werefa:queue:*")
        self._sub_task = asyncio.create_task(
            self._listen_loop(), name="werefa_redis_queue_sub"
        )
        logger.info("Real-time Redis pub/sub started for werefa:queue:*")

    async def _listen_loop(self) -> None:
        assert self._pub is not None
        while not self._stop.is_set():
            try:
                msg: dict[str, Any] | None = await self._pub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if not msg or msg.get("type") not in ("message", "pmessage"):
                    continue
                ch = msg.get("channel")
                data = msg.get("data")
                if ch is None or data is None:
                    continue
                if isinstance(ch, (bytes, bytearray)):
                    ch = ch.decode()
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode()
                if not isinstance(ch, str) or not ch.startswith("werefa:queue:"):
                    continue
                tail = ch.rsplit("werefa:queue:", 1)[-1]
                try:
                    sid = uuid.UUID(tail)
                except ValueError:
                    continue
                if isinstance(data, str):
                    await self._hub.local_publish(sid, data)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("redis queue sub loop")

    async def publish_to_channel(
        self, service_item_id: uuid.UUID, message: str
    ) -> None:
        if self._client is None:
            return
        await self._client.publish(_channel(service_item_id), message)

    async def shutdown(self) -> None:
        self._stop.set()
        if self._sub_task is not None:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass
            self._sub_task = None
        if self._pub is not None:
            await self._pub.punsubscribe()
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._pub = None
