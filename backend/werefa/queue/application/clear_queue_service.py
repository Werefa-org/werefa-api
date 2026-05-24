"""End-of-day / reset: close active tickets, hide chat, pause joins — keep analytics rows."""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from werefa.notifications.notifier import NotificationPayload
from werefa.queue.application.service import get_service_for_update
from werefa.shared.enums import DemandEventType, LivenessState, NotificationKind, TicketStatus
from werefa.shared.models import ClearQueueResult, Provider, QueueEntry, ServiceItem, User, utcnow

CLOSE_REASON_QUEUE_CLEARED = "queue_cleared"


def clear_service_line_queue(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> ClearQueueResult:
    """Close every active ticket, reset visible chat, pause remote joins.

    * Ticket rows are **not** deleted — ``close_reason=queue_cleared`` tags them.
    * Registered customers receive an inbox alert + optional email copy.
    * ``service_item.is_paused`` is set so the line starts fresh when resumed.
    """
    from werefa.analytics.application.service import record_demand_event
    from werefa.notifications.application import service as notifications_service
    from werefa.realtime.notify import notify_queue_subscribers

    svc = get_service_for_update(session, service_item_id)
    provider = session.get(Provider, svc.provider_id)
    biz_name = (provider.biz_name if provider else None) or "This business"
    service_label = svc.name

    now = utcnow()
    active = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .order_by(col(QueueEntry.ticket_number))
    ).all()

    notified = 0
    ticket_ids: list[str] = []
    body = (
        f"{biz_name} closed the {service_label} queue. "
        "You are no longer in line. Join again when the business reopens."
    )

    for ticket in active:
        ticket.status = TicketStatus.cancelled.value
        ticket.completed_at = now
        ticket.close_reason = CLOSE_REASON_QUEUE_CLEARED
        ticket.liveness_state = LivenessState.idle.value
        ticket.liveness_deadline_at = None
        session.add(ticket)
        ticket_ids.append(str(ticket.id))

        if ticket.user_id is None:
            continue
        user = session.get(User, ticket.user_id)
        if user is None or not user.is_active:
            continue
        notifications_service.dispatch(
            session,
            user=user,
            payload=NotificationPayload(
                kind=NotificationKind.queue_cleared,
                body=body,
                ticket_id=ticket.id,
                service_item_id=service_item_id,
            ),
        )
        notified += 1

    svc.line_chat_cleared_at = now
    svc.is_paused = True
    session.add(svc)

    if ticket_ids:
        record_demand_event(
            session,
            event_type=DemandEventType.queue_cleared,
            provider_id=svc.provider_id,
            service_item_id=service_item_id,
            payload={
                "cleared_count": len(ticket_ids),
                "ticket_ids": ticket_ids,
            },
        )

    session.commit()
    session.refresh(svc)

    notify_queue_subscribers(session, service_item_id, reason="queue_cleared")

    return ClearQueueResult(
        cleared_count=len(active),
        notified_count=notified,
        is_paused=True,
    )
