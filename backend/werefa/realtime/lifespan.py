import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from werefa.realtime.infrastructure.coordinator import RealtimeCoordinator

logger = logging.getLogger(__name__)

# Set during app startup for sync routes to schedule `publish` and for tests.
main_event_loop: asyncio.AbstractEventLoop | None = None
coordinator: RealtimeCoordinator | None = None


@asynccontextmanager
async def realtime_lifespan() -> AsyncIterator[None]:
    global main_event_loop, coordinator
    main_event_loop = asyncio.get_running_loop()
    c = RealtimeCoordinator.create()
    coordinator = c
    try:
        await c.start()
        logger.info(
            "Real-time stack ready: Redis=%s", c.uses_redis_pubsub
        )
        yield
    finally:
        if coordinator is not None:
            await coordinator.shutdown()
        coordinator = None
        main_event_loop = None
        logger.info("Real-time stack stopped")
