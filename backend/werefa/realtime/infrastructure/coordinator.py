import uuid
from dataclasses import dataclass, field

from werefa.core.config import settings
from werefa.realtime.infrastructure import redis_bridge
from werefa.realtime.infrastructure.hub import InMemoryQueueHub


@dataclass
class RealtimeCoordinator:
    """
    Single entry: publish a JSON string to all subscribers of a service line.
    - No Redis: deliver only to in-process WebSockets.
    - With Redis: publish to Redis; each process subscribes and fan-out locally, so
      we never double-emit to one worker.
    """

    hub: InMemoryQueueHub
    _redis: redis_bridge.RedisPubSubBackend | None = field(
        default=None, repr=False
    )

    async def start(self) -> None:
        if self._redis is not None:
            await self._redis.start()

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.shutdown()
        self._redis = None

    async def websocket_subscriber_snapshot(self) -> tuple[int, dict[str, int]]:
        return await self.hub.subscriber_snapshot()

    async def publish(self, service_item_id: uuid.UUID, message: str) -> int | None:
        """Fan out to this line's subscribers; report how many took it.

        ``None`` means "published, audience unknown" — the Redis path,
        where subscribers live on other replicas and no count comes back.
        That is deliberately distinct from ``0``, which is a real answer:
        the publish completed and reached nobody. A caller that treats
        those the same either texts people it did not need to or, worse,
        records an alert as delivered when nothing received it.
        """
        if self._redis is not None:
            await self._redis.publish_to_channel(service_item_id, message)
            return None
        return await self.hub.local_publish(service_item_id, message)

    def try_publish_now(
        self, service_item_id: uuid.UUID, message: str
    ) -> int | None:
        """Publish synchronously if that is possible, and say what it reached.

        For callers on the loop thread that must not claim delivery they
        haven't made and cannot await to find out. Returns a subscriber
        count only when the fan-out has actually completed — including
        ``0``, which is a completed fan-out to nobody.

        Without Redis the whole publish is a list snapshot and unbounded
        queue puts, so it finishes here with nothing left pending. With
        Redis it is a network round trip that genuinely needs the loop, and
        there is no honest synchronous answer — so this reports ``None``
        rather than scheduling something it cannot vouch for, and the caller
        falls back to a channel whose outcome it *can* confirm.

        Must be called on the event loop thread; see
        :meth:`InMemoryQueueHub.local_publish_nowait`.
        """
        if self._redis is not None:
            return None
        return self.hub.local_publish_nowait(service_item_id, message)

    @staticmethod
    def create() -> "RealtimeCoordinator":
        hub = InMemoryQueueHub()
        rds: redis_bridge.RedisPubSubBackend | None = None
        if settings.REALTIME_REDIS_URL not in (None, ""):
            rds = redis_bridge.RedisPubSubBackend(
                str(settings.REALTIME_REDIS_URL), hub
            )
        return RealtimeCoordinator(hub=hub, _redis=rds)

    @property
    def uses_redis_pubsub(self) -> bool:
        return self._redis is not None
