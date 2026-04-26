import asyncio
import logging
import uuid

from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.realtime.domain.events import QueueEventV1
from werefa.shared.enums import TicketStatus
from werefa.shared.models import QueueEntry

logger = logging.getLogger(__name__)


def _ticket_position(session: Session, ticket: QueueEntry) -> int | None:
    if ticket.status not in (TicketStatus.waiting.value, TicketStatus.serving.value):
        return None
    statement = (
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.service_item_id == ticket.service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(QueueEntry.ticket_number <= ticket.ticket_number)
    )
    count = session.exec(statement).one()
    if count is None or count < 1:
        return None
    return int(count)


def notify_queue_subscribers(
    session: Session,
    service_item_id: uuid.UUID,
    *,
    ticket: QueueEntry | None = None,
    reason: str | None = None,
) -> None:
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    text = QueueEventV1.build(
        service_item_id,
        ticket_id=ticket.id if ticket else None,
        status=ticket.status if ticket else None,
        position=_ticket_position(session, ticket) if ticket else None,
        reason=reason,
    ).model_dump_json()
    t = loop.create_task(c.publish(service_item_id, text))

    def _log_done(done: asyncio.Task[object]) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Real-time fan-out task failed")

    t.add_done_callback(_log_done)
