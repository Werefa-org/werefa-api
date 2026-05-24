import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlmodel import col, select

from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.notifications.application import service as notifications_service
from werefa.queue.application import join_invite_service
from werefa.queue.application import line_chat_service
from werefa.queue.application import liveness_service
from werefa.queue.application import snapshot_service
from werefa.queue.application import kiosk_batch_service
from werefa.queue.application import service as queue_service
from werefa.queue.application.serializers import queue_entry_to_public
from werefa.realtime.notify import notify_queue_subscribers
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    JoinInviteCreate,
    JoinInviteCreated,
    KioskSyncBatchIn,
    KioskSyncBatchOut,
    LineChatCreate,
    LineChatMessagePublic,
    LineChatMessagesPublic,
    LivenessPublic,
    PositionPingCreate,
    QueueEntriesPublic,
    QueueEntry,
    QueueEntryPublic,
    QueueJoin,
    ServiceItem,
    TicketPriorityUpdate,
    TicketQueueSnapshot,
    TicketStatusUpdate,
    WalkInCreate,
)

router = APIRouter(prefix="/service-items", tags=["queue"])


def _service_or_404(session: SessionDep, service_item_id: uuid.UUID) -> ServiceItem:
    row = session.get(ServiceItem, service_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


@router.get("/me/tickets", response_model=QueueEntriesPublic)
def my_active_tickets(*, session: SessionDep, current_user: CurrentUser) -> Any:
    statement = (
        select(QueueEntry)
        .where(QueueEntry.user_id == current_user.id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .order_by(col(QueueEntry.joined_at))
    )
    rows = session.exec(statement).all()
    data = [queue_entry_to_public(session, r) for r in rows]
    return QueueEntriesPublic(data=data, count=len(data))


@router.post("/{service_item_id}/join", response_model=QueueEntryPublic)
def join_queue(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    body: QueueJoin,
) -> Any:
    _service_or_404(session, service_item_id)
    ticket = queue_service.join_queue_remote(
        session,
        service_item_id=service_item_id,
        user=current_user,
        access_code=body.access_code,
        latitude=body.latitude,
        longitude=body.longitude,
        invite_token=body.invite_token,
        vip_code=body.vip_code,
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="join"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(ticket)


@router.post(
    "/{service_item_id}/join-invites",
    response_model=JoinInviteCreated,
)
def create_join_invite(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    body: JoinInviteCreate,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    row = join_invite_service.create_invite(
        session,
        service_item_id=service_item_id,
        ttl_hours=body.ttl_hours,
    )
    return JoinInviteCreated(token=row.token, expires_at=row.expires_at)


@router.post(
    "/{service_item_id}/kiosk-sync-batch",
    response_model=KioskSyncBatchOut,
)
def kiosk_sync_batch(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    body: KioskSyncBatchIn,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    out = kiosk_batch_service.ingest_kiosk_walk_in_batch(
        session, service_item_id=service_item_id, body=body
    )
    notify_queue_subscribers(session, service_item_id, reason="walk_in_batch")
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return out


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/position",
    response_model=QueueEntryPublic,
)
def submit_position_ping(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: PositionPingCreate,
) -> Any:
    _service_or_404(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the ticket holder can submit position pings",
        )
    row = liveness_service.record_position_ping(
        session,
        ticket_id=ticket_id,
        service_item_id=service_item_id,
        user=current_user,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy_m=body.accuracy_m,
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=row, reason="liveness_ping"
    )
    background_tasks.add_task(
        notifications_service.run_evaluate_smart_alerts_for_service_line,
        service_item_id,
    )
    return QueueEntryPublic.model_validate(row)


@router.get(
    "/{service_item_id}/chat/messages",
    response_model=LineChatMessagesPublic,
)
def list_line_chat_messages(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    _service_or_404(session, service_item_id)
    rows, enabled = line_chat_service.list_messages(
        session, service_item_id=service_item_id, user=current_user
    )
    return LineChatMessagesPublic(
        data=rows, count=len(rows), line_chat_enabled=enabled
    )


@router.post(
    "/{service_item_id}/chat/messages",
    response_model=LineChatMessagePublic,
    status_code=status.HTTP_201_CREATED,
)
def post_line_chat_message(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    body: LineChatCreate,
) -> Any:
    _service_or_404(session, service_item_id)
    return line_chat_service.post_message(
        session,
        service_item_id=service_item_id,
        user=current_user,
        body=body,
    )


@router.get(
    "/{service_item_id}/tickets/{ticket_id}/snapshot",
    response_model=TicketQueueSnapshot,
)
def read_ticket_queue_snapshot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    _service_or_404(session, service_item_id)
    return snapshot_service.build_ticket_queue_snapshot(
        session,
        service_item_id=service_item_id,
        ticket_id=ticket_id,
        user=current_user,
    )


@router.get(
    "/{service_item_id}/tickets/{ticket_id}/liveness",
    response_model=LivenessPublic,
)
def read_ticket_liveness(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.user_id is None:
        ensure_provider_staff(
            session=session,
            current_user=current_user,
            provider_id=svc.provider_id,
        )
    elif not current_user.is_superuser and ticket.user_id != current_user.id:
        ensure_provider_staff(
            session=session,
            current_user=current_user,
            provider_id=svc.provider_id,
        )
    t, last = liveness_service.read_liveness(
        session, ticket_id=ticket_id, service_item_id=service_item_id
    )
    return LivenessPublic(
        ticket_id=t.id,
        liveness_state=t.liveness_state,
        liveness_deadline_at=t.liveness_deadline_at,
        last_ping_at=last.sent_at if last else None,
        last_latitude=last.latitude if last else None,
        last_longitude=last.longitude if last else None,
        last_accuracy_m=last.accuracy_m if last else None,
    )


@router.post("/{service_item_id}/walk-in", response_model=QueueEntryPublic)
def register_walk_in(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    body: WalkInCreate,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    ticket = queue_service.join_queue_walk_in(
        session,
        service_item_id=service_item_id,
        guest_name=body.guest_name,
        is_vip=body.is_vip,
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="walk_in"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(ticket)


@router.patch(
    "/{service_item_id}/tickets/{ticket_id}/priority",
    response_model=QueueEntryPublic,
)
def set_ticket_priority(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: TicketPriorityUpdate,
) -> Any:
    """Staff can manually promote a ticket to VIP (priority=1) or demote it (priority=0)."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    ticket = queue_service.set_ticket_priority(
        session,
        service_item_id=service_item_id,
        ticket_id=ticket_id,
        priority=body.priority,
    )
    notify_queue_subscribers(session, service_item_id, ticket=ticket, reason="priority_change")
    return QueueEntryPublic.model_validate(ticket)


@router.get("/{service_item_id}/tickets", response_model=QueueEntriesPublic)
def list_tickets_for_service(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    rows = queue_service.list_queue_entries(session, service_item_id)
    data = [QueueEntryPublic.model_validate(r) for r in rows]
    return QueueEntriesPublic(data=data, count=len(data))


@router.post("/{service_item_id}/call-next", response_model=QueueEntryPublic | None)
def call_next(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    current, nxt = queue_service.call_next_transition(session, service_item_id)
    if current is not None:
        notify_queue_subscribers(
            session, service_item_id, ticket=current, reason="call_next"
        )
    if nxt is not None:
        notify_queue_subscribers(
            session, service_item_id, ticket=nxt, reason="call_next"
        )
        notifications_service.notify_ticket_now_serving(
            session, ticket=nxt, service_item_id=service_item_id
        )
    if current is None and nxt is None:
        notify_queue_subscribers(session, service_item_id, reason="call_next")
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    if nxt is None:
        return None
    return QueueEntryPublic.model_validate(nxt)


@router.post("/{service_item_id}/recall", response_model=QueueEntryPublic)
def recall_customer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    """FR-09: re-open the last completed ticket within a short staff-only window."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    row = queue_service.recall_last_completed(session, service_item_id)
    notify_queue_subscribers(
        session, service_item_id, ticket=row, reason="recall"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(row)


@router.delete(
    "/{service_item_id}/tickets/{ticket_id}",
    response_model=QueueEntryPublic,
)
def cancel_my_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    """Customer leaves their own queue spot (CRIT-4).

    Owner-only — staff use the PATCH endpoint to mark no-show or
    complete. No strike is recorded for a voluntary cancel.
    """
    _service_or_404(session, service_item_id)
    ticket = queue_service.cancel_my_ticket(
        session, ticket_id=ticket_id, user=current_user
    )
    if ticket.service_item_id != service_item_id:
        # Defensive: should be impossible but keeps the URL contract
        # honest if a client mismatched ids.
        raise HTTPException(
            status_code=404,
            detail="Ticket does not belong to this service line",
        )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="cancelled_by_user"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(ticket)


@router.patch(
    "/{service_item_id}/tickets/{ticket_id}/status",
    response_model=QueueEntryPublic,
)
def update_ticket_status(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: TicketStatusUpdate,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    row = queue_service.set_ticket_status(
        session, ticket_id, service_item_id, body.status
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=row, reason="status_update"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(row)
