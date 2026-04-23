import asyncio
import logging
import uuid

from werefa.realtime.domain.events import QueueEventV1

logger = logging.getLogger(__name__)


def notify_queue_subscribers(
    service_item_id: uuid.UUID, *, reason: str | None = None
) -> None:
    """
    From sync request handlers. Schedules a JSON event on the main asyncio loop.
    Safe to call if lifespans are not started (e.g. some unit tests): no-op.
    """
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    text = QueueEventV1.build(service_item_id, reason=reason).model_dump_json()
    t = loop.create_task(c.publish(service_item_id, text))

    def _log_done(done: asyncio.Task[object]) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Real-time fan-out task failed")

    t.add_done_callback(_log_done)
