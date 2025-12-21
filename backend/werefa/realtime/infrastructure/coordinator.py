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

    async def publish(self, service_item_id: uuid.UUID, message: str) -> None:
        if self._redis is not None:
            await self._redis.publish_to_channel(service_item_id, message)
        else:
            await self.hub.local_publish(service_item_id, message)

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
