"""End-of-day / reset: close active tickets, hide chat, pause joins — keep analytics rows."""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from werefa.notifications.notifier import NotificationPayload
from werefa.queue.application.service import get_service_for_update
from werefa.queue.domain import ticket_rules
from werefa.shared.enums import DemandEventType, LivenessState, NotificationKind, TicketStatus
from werefa.shared.models import (
    ClearQueueResult,
    Provider,
    QueueEntry,
    ReopenQueueResult,
    ServiceItem,
    User,
    utcnow,
)

CLOSE_REASON_QUEUE_CLEARED = "queue_cleared"


def clear_service_line_queue(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> ClearQueueResult:
    """Close every active ticket, reset visible chat, pause remote joins.

    * Ticket rows are **not** deleted — ``close_reason=queue_cleared`` tags them.
    * Registered customers receive an inbox alert + optional email copy.
    * ``service_item.is_paused`` is set; :func:`reopen_service_line_queue`
      lifts it again.

    "Active" here means :func:`ticket_rules.active_status_values` — the same
    set the rest of the queue uses, which includes ``pending_approval``. A
    join awaiting staff review is an active ticket everywhere else: it holds
    the customer's one-active-ticket slot (application check *and* the
    ``ix_queue_entry_one_active_user`` partial index) and it shows up in the
    staff ticket list. Closing only ``waiting``/``serving`` left those rows
    behind, so staff came back to approval requests for a day that had
    already ended, and the customers behind them were refused their next
    remote join with "You already have an active ticket in a queue" — a
    reopen could not clear it, because nothing in the reopen path touches
    tickets.
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
        .where(col(QueueEntry.status).in_(ticket_rules.active_status_values()))
        .order_by(col(QueueEntry.ticket_number))
    ).all()

    notified = 0
    ticket_ids: list[str] = []
    in_line_body = (
        f"{biz_name} closed the {service_label} queue. "
        "You are no longer in line. Join again when the business reopens."
    )
    # Someone still awaiting approval was never *in* line, so telling them
    # they lost their place is wrong twice over — they had none, and the
    # actionable part is that the request will not be reviewed today.
    pending_body = (
        f"{biz_name} closed the {service_label} queue before reviewing your "
        "join request. It was not approved. Request to join again when the "
        "business reopens."
    )

    for ticket in active:
        was_pending = ticket.status == TicketStatus.pending_approval.value
        ticket.status = TicketStatus.cancelled.value
        ticket.completed_at = now
        ticket.close_reason = CLOSE_REASON_QUEUE_CLEARED
        ticket.liveness_state = LivenessState.idle.value
        ticket.liveness_deadline_at = None
        # A closed ticket cannot be parked. Call Next clears the hold when it
        # settles a ticket; closing one has to do the same, or the staff panel
        # keeps rendering a hold countdown for a line that is shut.
        ticket.liveness_hold_until = None
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
                body=pending_body if was_pending else in_line_body,
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


def reopen_service_line_queue(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> ReopenQueueResult:
    """Lift the pause :func:`clear_service_line_queue` set — the next morning.

    Deliberately the exact inverse of the clear and nothing more: it does
    **not** revive cleared tickets (they are closed for good, with
    ``close_reason=queue_cleared``) and it does not reset ticket numbering.

    It also does not touch ``provider.is_paused``. That flag is business-wide
    and has its own pause/resume pair; a line reopening cannot decide the
    whole business is open. But the two pauses are independent and a caller
    that only lifted one will still see remote joins refused, so the result
    reports both — ``remote_joins_open`` is the answer to the question staff
    are actually asking.
    """
    from werefa.realtime.notify import notify_queue_subscribers

    svc = get_service_for_update(session, service_item_id)
    provider = session.get(Provider, svc.provider_id)

    was_paused = svc.is_paused
    svc.is_paused = False
    session.add(svc)
    session.commit()
    session.refresh(svc)

    if was_paused:
        notify_queue_subscribers(session, service_item_id, reason="queue_reopened")

    provider_paused = bool(provider and provider.is_paused)
    return ReopenQueueResult(
        is_paused=False,
        provider_is_paused=provider_paused,
        remote_joins_open=svc.is_active
        and not provider_paused
        and bool(provider and provider.is_open),
    )
