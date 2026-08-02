import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlmodel import col, select

from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.notifications.application import service as notifications_service
from werefa.queue.application import join_invite_service
from werefa.queue.application import line_chat_service
from werefa.queue.application import liveness_service
from werefa.queue.application import snapshot_service
from werefa.queue.application import clear_queue_service
from werefa.queue.application import customer_governance_service
from werefa.queue.application import kiosk_batch_service
from werefa.queue.application import join_documents_service
from werefa.queue.application import service as queue_service
from werefa.queue.application.serializers import queue_entry_to_public
from werefa.realtime.notify import notify_queue_subscribers
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    ClearQueueResult,
    JoinInviteCreate,
    JoinInviteCreated,
    KioskSyncBatchIn,
    KioskSyncBatchOut,
    LineChatCreate,
    LineChatMessagePublic,
    LineChatMessagesPublic,
    LivenessBoardPublic,
    LivenessBoardRow,
    LivenessHoldCreate,
    LivenessHoldResult,
    LivenessPublic,
    PositionPingCreate,
    QueueEntriesPublic,
    QueueEntry,
    NotifyTicketResult,
    QueueEntryPublic,
    QueueJoin,
    ReopenQueueResult,
    ServiceItem,
    TicketPriorityUpdate,
    TicketQueueSnapshot,
    TicketStatusUpdate,
    WalkInCreate,
    ProviderBanCreate,
    ProviderCustomersPublic,
    TicketApprovalBody,
    TicketJoinDocumentsPublic,
    ServiceLinePreview,
)

router = APIRouter(prefix="/service-items", tags=["queue"])


def _service_or_404(session: SessionDep, service_item_id: uuid.UUID) -> ServiceItem:
    row = session.get(ServiceItem, service_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


@router.get(
    "/{service_item_id}/line-preview",
    response_model=ServiceLinePreview,
)
def read_service_line_preview(
    *,
    session: SessionDep,
    service_item_id: uuid.UUID,
) -> Any:
    """Public queue stats before joining (no auth)."""
    return snapshot_service.build_service_line_preview(
        session, service_item_id=service_item_id
    )


@router.get("/me/tickets", response_model=QueueEntriesPublic)
def my_active_tickets(*, session: SessionDep, current_user: CurrentUser) -> Any:
    statement = (
        select(QueueEntry)
        .where(QueueEntry.user_id == current_user.id)
        .where(
            col(QueueEntry.status).in_(
                (
                    TicketStatus.waiting.value,
                    TicketStatus.serving.value,
                    TicketStatus.pending_approval.value,
                )
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
    if ticket.status != TicketStatus.pending_approval.value:
        notifications_service.evaluate_smart_alerts_for_service_line(
            session, service_item_id=service_item_id
        )
    return queue_entry_to_public(session, ticket)


@router.post(
    "/{service_item_id}/join-with-files",
    response_model=QueueEntryPublic,
)
async def join_queue_with_files(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    access_code: str | None = Form(default=None),
    vip_code: str | None = Form(default=None),
    invite_token: str | None = Form(default=None),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    documents: list[UploadFile] = File(...),
) -> Any:
    svc = _service_or_404(session, service_item_id)
    join_documents_service.assert_join_documents_ready(svc, documents)
    ticket = queue_service.join_queue_remote(
        session,
        service_item_id=service_item_id,
        user=current_user,
        access_code=access_code,
        latitude=latitude,
        longitude=longitude,
        invite_token=invite_token,
        vip_code=vip_code,
        skip_document_check=True,  # files validated and stored below
    )
    requirements = join_documents_service.parse_requirements(
        svc.join_document_requirements
    )
    await join_documents_service.store_ticket_join_documents(
        session,
        ticket_id=ticket.id,
        service_item_id=service_item_id,
        requirements=requirements,
        uploads=documents,
    )
    session.refresh(ticket)
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="join"
    )
    if ticket.status != TicketStatus.pending_approval.value:
        notifications_service.evaluate_smart_alerts_for_service_line(
            session, service_item_id=service_item_id
        )
    return queue_entry_to_public(session, ticket)


@router.get(
    "/{service_item_id}/tickets/{ticket_id}/documents",
    response_model=TicketJoinDocumentsPublic,
)
def list_ticket_join_documents(
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
    if ticket.user_id != current_user.id:
        ensure_provider_staff(
            session=session,
            current_user=current_user,
            provider_id=svc.provider_id,
        )
    rows = join_documents_service.list_ticket_join_documents(
        session, ticket_id=ticket_id
    )
    return TicketJoinDocumentsPublic(data=rows, count=len(rows))


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
    body: PositionPingCreate | None = None,
) -> Any:
    """Customer check-in — "I'm on my way".

    Coordinates are optional and an empty body is valid: a device with no
    location fix must still be able to keep its spot, otherwise a denied
    permission reads to staff exactly like walking away.
    """
    _service_or_404(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the ticket holder can submit position pings",
        )
    body = body or PositionPingCreate()
    was_held = ticket.liveness_hold_until is not None
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
        session,
        service_item_id,
        ticket=row,
        # ``liveness_restored`` is reserved for a check-in that actually
        # unparked the spot, which is the transition boards need to redraw:
        # the ticket is callable again. A check-in with no hold in play is
        # just ``liveness_ping``. The reason must track what changed in the
        # row — announcing "restored" while Call Next still skipped the
        # ticket is what had boards showing customers back in line who then
        # never got called.
        reason="liveness_restored" if was_held else "liveness_ping",
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
    t, last, rec = liveness_service.read_liveness(
        session,
        ticket_id=ticket_id,
        service_item_id=service_item_id,
        # The owner opening their own ticket is proof the app is alive, so
        # this read counts as contact.
        seen_by_owner=ticket.user_id is not None
        and ticket.user_id == current_user.id,
    )
    return LivenessPublic(
        ticket_id=t.id,
        liveness_state=t.liveness_state,
        liveness_deadline_at=t.liveness_deadline_at,
        last_ping_at=last.sent_at if last else None,
        last_latitude=last.latitude if last else None,
        last_longitude=last.longitude if last else None,
        last_accuracy_m=last.accuracy_m if last else None,
        last_seen_at=t.liveness_last_seen_at,
        misses=t.liveness_misses,
        hold_until=t.liveness_hold_until,
        hold_count=t.liveness_hold_count,
        recommended_action=rec.action.value,
        recommended_reason=rec.reason,
        can_hold=rec.can_hold,
    )


@router.get(
    "/{service_item_id}/liveness/board",
    response_model=LivenessBoardPublic,
)
def read_liveness_board(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    """Staff view: everyone about to be called, and what to do about them."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    rows = [
        LivenessBoardRow.model_validate(r)
        for r in liveness_service.build_liveness_board(session, service_item_id)
    ]
    return LivenessBoardPublic(data=rows, count=len(rows))


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/liveness/hold",
    response_model=LivenessHoldResult,
)
def hold_ticket_spot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: LivenessHoldCreate | None = None,
) -> Any:
    """Park a spot so the line moves on without dropping the customer.

    The ticket stays ``waiting`` and no strike is recorded — the only path
    to a strike is still calling the customer and marking a no-show.
    """
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    body = body or LivenessHoldCreate()
    ticket = liveness_service.hold_ticket(
        session,
        ticket_id=ticket_id,
        service_item_id=service_item_id,
        hold_seconds=body.hold_seconds,
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="liveness_hold"
    )
    return LivenessHoldResult(
        ticket_id=ticket.id,
        status=ticket.status,
        hold_until=ticket.liveness_hold_until,
        hold_count=ticket.liveness_hold_count,
        message="Spot held — the next customer will be called.",
    )


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/liveness/release",
    response_model=LivenessHoldResult,
)
def release_ticket_hold(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    """Customer turned up: unpark the spot immediately."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    ticket = liveness_service.release_hold(
        session, ticket_id=ticket_id, service_item_id=service_item_id
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="liveness_restored"
    )
    return LivenessHoldResult(
        ticket_id=ticket.id,
        status=ticket.status,
        hold_until=ticket.liveness_hold_until,
        hold_count=ticket.liveness_hold_count,
        message="Hold released — the ticket is callable again.",
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
        guest_phone=body.guest_phone,
        guest_email=body.guest_email,
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
    # A priority change *is* a change to who gets called next, so it owes
    # the line the same alert pass every other queue mutation runs. Without
    # it the customer a VIP bump just moved to the front was never told —
    # the counter called someone who had no idea they were next.
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return QueueEntryPublic.model_validate(ticket)


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/notify",
    response_model=NotifyTicketResult,
)
def notify_waiting_customer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    """Send a you-are-next notification to a waiting app customer."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    notifications_service.notify_ticket_staff_you_are_next(
        session,
        ticket=ticket,
        service_item_id=service_item_id,
    )
    return NotifyTicketResult()


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
    data = [queue_entry_to_public(session, r) for r in rows]
    return QueueEntriesPublic(data=data, count=len(data))


@router.post("/{service_item_id}/clear-queue", response_model=ClearQueueResult)
def clear_queue(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    """End-of-day reset: close active tickets, hide chat, pause joins (data retained)."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    return clear_queue_service.clear_service_line_queue(
        session, service_item_id=service_item_id
    )


@router.post("/{service_item_id}/reopen-queue", response_model=ReopenQueueResult)
def reopen_queue(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
) -> Any:
    """Undo the end-of-day pause from ``clear-queue``; cleared tickets stay closed."""
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    return clear_queue_service.reopen_service_line_queue(
        session, service_item_id=service_item_id
    )


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
    return queue_entry_to_public(session, row)


@router.get(
    "/{service_item_id}/customers",
    response_model=ProviderCustomersPublic,
)
def list_queue_customers(
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
    return customer_governance_service.list_provider_customers(
        session, provider_id=svc.provider_id, service_item_id=service_item_id
    )


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/approve",
    response_model=QueueEntryPublic,
)
def approve_join_request(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    body: TicketApprovalBody | None = None,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    order = body.queue_order if body else None
    ticket = customer_governance_service.approve_ticket(
        session,
        service_item_id=service_item_id,
        ticket_id=ticket_id,
        approver=current_user,
        queue_order=order,
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="join_approved"
    )
    notifications_service.evaluate_smart_alerts_for_service_line(
        session, service_item_id=service_item_id
    )
    return queue_entry_to_public(session, ticket)


@router.post(
    "/{service_item_id}/tickets/{ticket_id}/reject",
    response_model=QueueEntryPublic,
)
def reject_join_request(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> Any:
    svc = _service_or_404(session, service_item_id)
    ensure_provider_staff(
        session=session,
        current_user=current_user,
        provider_id=svc.provider_id,
    )
    ticket = customer_governance_service.reject_ticket(
        session, service_item_id=service_item_id, ticket_id=ticket_id
    )
    notify_queue_subscribers(
        session, service_item_id, ticket=ticket, reason="join_rejected"
    )
    return queue_entry_to_public(session, ticket)
