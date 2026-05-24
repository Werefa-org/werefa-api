import asyncio
import logging
import uuid
from collections.abc import Iterable

from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.realtime.domain.events import (
    BroadcastEventV1,
    LineChatEventV1,
    QueueEventV1,
)
from werefa.shared.enums import TicketStatus
from werefa.shared.models import QueueEntry, utcnow

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


def notify_broadcast_subscribers(
    *,
    broadcast_id: uuid.UUID,
    provider_id: uuid.UUID,
    body_text: str,
    severity: str,
    author_role: str = "staff",
    author_label: str = "Business",
    service_item_ids: Iterable[uuid.UUID],
    original_service_item_id: uuid.UUID | None,
) -> None:
    """Best-effort fan-out of a broadcast to one or more service-line channels.

    Failures are logged but never raise — the broadcast row is already
    persisted and reachable through the REST list endpoint.
    """
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    occurred_at = utcnow()
    for sid in service_item_ids:
        role: str = author_role if author_role in ("owner", "staff") else "staff"
        event = BroadcastEventV1(
            broadcast_id=broadcast_id,
            provider_id=provider_id,
            # Wire-level: name the *channel* this delivery uses so clients
            # always have a concrete service line to filter on. The
            # persisted record keeps `original_service_item_id` truthful.
            service_item_id=sid if original_service_item_id is not None else sid,
            body=body_text,
            severity=_severity_literal(severity),
            author_role=role,  # type: ignore[arg-type]
            author_label=author_label,
            occurred_at=occurred_at,
        )
        text = event.model_dump_json()
        task = loop.create_task(c.publish(sid, text))

        def _log_done(done: asyncio.Task[object]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Broadcast fan-out task failed")

        task.add_done_callback(_log_done)


def notify_line_chat_subscribers(
    *,
    message_id: uuid.UUID,
    service_item_id: uuid.UUID,
    body_text: str,
    author_role: str,
    author_label: str,
    author_user_id: uuid.UUID,
) -> None:
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    occurred_at = utcnow()
    event = LineChatEventV1(
        message_id=message_id,
        service_item_id=service_item_id,
        author_user_id=author_user_id,
        body=body_text,
        author_role=author_role[:32],
        author_label=author_label[:200],
        occurred_at=occurred_at,
    )
    text = event.model_dump_json()
    task = loop.create_task(c.publish(service_item_id, text))

    def _log_done(done: asyncio.Task[object]) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Line chat fan-out task failed")

    task.add_done_callback(_log_done)


def _severity_literal(value: str) -> str:
    """Narrow ``str`` to the BroadcastEventV1 Literal at the boundary.

    The pydantic Literal validation will reject anything else, but we
    fall back to ``info`` to keep the realtime layer permissive when
    fed unexpected input from upstream changes.
    """
    if value in ("info", "warning", "critical"):
        return value
    return "info"
