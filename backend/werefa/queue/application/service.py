import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from werefa.queue.domain import ticket_rules
from werefa.shared.enums import TicketSource, TicketStatus
from werefa.shared.models import Provider, QueueEntry, ServiceItem, User, utcnow
from werefa.strikes.application import service as strikes_service


def _is_one_active_user_unique_violation(err: IntegrityError) -> bool:
    """
    Distinguish partial unique (one active app ticket per user) from other integrity errors.
    """
    orig = err.orig
    if orig is not None:
        if getattr(orig, "pgcode", None) == "23505":
            return True
        s = str(orig)
        if "ix_queue_entry_one_active_user" in s:
            return True
    combined = f"{err} {orig or ''}"
    if "ix_queue_entry_one_active_user" in combined:
        return True
    low = combined.lower()
    if "unique" in low and "queue_entry" in low:
        return True
    return False


def assert_single_active_ticket(session: Session, user_id: uuid.UUID) -> None:
    statement = (
        select(QueueEntry.id)
        .where(QueueEntry.user_id == user_id)
        .where(col(QueueEntry.status).in_(ticket_rules.active_status_values()))
    )
    if session.exec(statement).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active ticket in a queue",
        )


def get_service_for_update(session: Session, service_item_id: uuid.UUID) -> ServiceItem:
    statement = (
        select(ServiceItem).where(ServiceItem.id == service_item_id).with_for_update()
    )
    row = session.exec(statement).first()
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


def join_queue_remote(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    user: User,
    access_code: str | None,
) -> QueueEntry:
    svc = get_service_for_update(session, service_item_id)
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is not active")

    provider = session.get(Provider, svc.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not provider.is_open or provider.is_paused:
        raise HTTPException(
            status_code=400, detail="Provider is not accepting joins right now"
        )

    if provider.is_private:
        if not access_code or access_code != (provider.access_code or ""):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing access code",
            )

    # FR-12: penalty enforcement runs *before* we touch the row lock so a
    # blocked user pays no contention cost on the service row.
    strikes_service.assert_remote_join_allowed(session=session, user=user)

    assert_single_active_ticket(session, user.id)

    num = svc.next_ticket_number
    svc.next_ticket_number = num + 1
    session.add(svc)

    ticket = QueueEntry(
        service_item_id=service_item_id,
        user_id=user.id,
        ticket_number=num,
        status=TicketStatus.waiting.value,
        source=TicketSource.remote_app.value,
        guest_name=None,
    )
    session.add(ticket)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        # Races: application check and partial unique index ix_queue_entry_one_active_user
        if _is_one_active_user_unique_violation(err):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an active ticket in a queue",
            ) from None
        raise
    session.refresh(ticket)
    return ticket


def join_queue_walk_in(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    guest_name: str | None,
) -> QueueEntry:
    svc = get_service_for_update(session, service_item_id)
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is not active")

    provider = session.get(Provider, svc.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not provider.is_open or provider.is_paused:
        raise HTTPException(
            status_code=400, detail="Provider is not accepting joins right now"
        )

    num = svc.next_ticket_number
    svc.next_ticket_number = num + 1
    session.add(svc)

    ticket = QueueEntry(
        service_item_id=service_item_id,
        user_id=None,
        ticket_number=num,
        status=TicketStatus.waiting.value,
        source=TicketSource.kiosk_walk_in.value,
        guest_name=guest_name,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def list_queue_entries(
    session: Session, service_item_id: uuid.UUID
) -> Sequence[QueueEntry]:
    statement = (
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .order_by(col(QueueEntry.joined_at))
    )
    return session.exec(statement).all()


def call_next(session: Session, service_item_id: uuid.UUID) -> QueueEntry | None:
    _, nxt = call_next_transition(session, service_item_id)
    return nxt


def call_next_transition(
    session: Session, service_item_id: uuid.UUID
) -> tuple[QueueEntry | None, QueueEntry | None]:
    get_service_for_update(session, service_item_id)

    current = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.serving.value)
        .order_by(col(QueueEntry.joined_at))
    ).first()

    if current:
        current.status = TicketStatus.completed.value
        current.completed_at = utcnow()
        session.add(current)

    nxt = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.waiting.value)
        .order_by(col(QueueEntry.joined_at))
    ).first()

    if not nxt:
        session.commit()
        if current is not None:
            session.refresh(current)
        return current, None

    nxt.status = TicketStatus.serving.value
    session.add(nxt)
    session.commit()
    if current is not None:
        session.refresh(current)
    session.refresh(nxt)
    return current, nxt


def set_ticket_status(
    session: Session,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    new_status: TicketStatus,
) -> QueueEntry:
    ticket = session.get(QueueEntry, ticket_id)
    if not ticket or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    try:
        ticket_rules.validate_manual_status_change(ticket.status, new_status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    ticket.status = new_status.value
    ticket.completed_at = utcnow()

    session.add(ticket)

    # FR-12: a no-show transition also accrues a strike for registered users.
    # Recorded *before* commit so the strike row and status update share a
    # single transaction.
    if new_status == TicketStatus.no_show:
        svc = session.get(ServiceItem, ticket.service_item_id)
        provider_id = svc.provider_id if svc is not None else None
        if provider_id is not None:
            strikes_service.record_no_show(
                session=session, ticket=ticket, provider_id=provider_id
            )

    session.commit()
    session.refresh(ticket)
    return ticket
