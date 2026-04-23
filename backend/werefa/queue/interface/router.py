import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.queue.application import service as queue_service
from werefa.realtime.notify import notify_queue_subscribers
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    QueueEntriesPublic,
    QueueEntry,
    QueueEntryPublic,
    QueueJoin,
    ServiceItem,
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
    data = [QueueEntryPublic.model_validate(r) for r in rows]
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
    )
    notify_queue_subscribers(service_item_id, reason="join")
    return QueueEntryPublic.model_validate(ticket)


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
    )
    notify_queue_subscribers(service_item_id, reason="walk_in")
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
    nxt = queue_service.call_next(session, service_item_id)
    notify_queue_subscribers(service_item_id, reason="call_next")
    if nxt is None:
        return None
    return QueueEntryPublic.model_validate(nxt)


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
    notify_queue_subscribers(service_item_id, reason="status_update")
    return QueueEntryPublic.model_validate(row)
