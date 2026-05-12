import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application import customer_governance_service
from werefa.queue.application import join_invite_service
from werefa.queue.domain import ticket_rules
from werefa.shared.enums import TicketSource, TicketStatus
from werefa.shared.models import Provider, QueueEntry, Review, ServiceItem, User, utcnow
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
    vip_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    invite_token: str | None = None,
    skip_document_check: bool = False,
) -> QueueEntry:
    svc = get_service_for_update(session, service_item_id)
    if svc.requires_join_documents and not skip_document_check:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This line requires document uploads. "
                "Use the join form and attach each requested file."
            ),
        )
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is not active")

    provider = session.get(Provider, svc.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not provider.is_open:
        raise HTTPException(
            status_code=400, detail="This business is currently closed"
        )

    if svc.is_paused or provider.is_paused:
        raise HTTPException(
            status_code=400, detail="This service is not accepting remote joins right now"
        )

    is_private = svc.is_private or provider.is_private
    if is_private:
        invite_ok = join_invite_service.assert_invite_valid_for_service(
            session, token=invite_token, service_item_id=service_item_id
        )
        code_ok = bool(
            access_code and access_code == (provider.access_code or "")
        )
        if not code_ok and not invite_ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing access code",
            )

    if provider.join_radius_m is not None:
        if provider.latitude is None or provider.longitude is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This business uses a join distance limit but has no map "
                    "coordinates configured"
                ),
            )
        if latitude is None or longitude is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Share your latitude and longitude to join this queue remotely"
                ),
            )
        distance_m = provider_repo.distance_meters(
            base_lat=provider.latitude,
            base_lon=provider.longitude,
            target_lat=latitude,
            target_lon=longitude,
        )
        if distance_m > provider.join_radius_m:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are too far from this business to join remotely",
            )

    # FR-12: penalty enforcement runs *before* we touch the row lock so a
    # blocked user pays no contention cost on the service row.
    strikes_service.assert_remote_join_allowed(session=session, user=user)
    customer_governance_service.assert_not_banned(
        session, provider_id=provider.id, user_id=user.id
    )

    assert_single_active_ticket(session, user.id)

    invite_ok = join_invite_service.assert_invite_valid_for_service(
        session, token=invite_token, service_item_id=service_item_id
    )
    source = (
        TicketSource.qr_scan.value if invite_ok else TicketSource.remote_app.value
    )

    # VIP priority: code must match and service must have VIP enabled
    is_vip = (
        svc.allow_vip
        and bool(vip_code)
        and bool(svc.vip_code)
        and vip_code.strip().upper() == svc.vip_code.strip().upper()
    )

    needs_approval = svc.requires_join_approval
    initial_status = (
        TicketStatus.pending_approval.value
        if needs_approval
        else TicketStatus.waiting.value
    )

    num = svc.next_ticket_number
    svc.next_ticket_number = num + 1
    session.add(svc)

    ticket = QueueEntry(
        service_item_id=service_item_id,
        user_id=user.id,
        ticket_number=num,
        status=initial_status,
        source=source,
        guest_name=user.full_name,
        priority=1 if is_vip else 0,
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
    from werefa.analytics.application.service import record_demand_event
    from werefa.shared.enums import DemandEventType

    record_demand_event(
        session,
        event_type=(
            DemandEventType.join_qr if invite_ok else DemandEventType.join_remote
        ),
        provider_id=provider.id,
        service_item_id=service_item_id,
        user_id=user.id,
        payload={"ticket_id": str(ticket.id)},
    )
    return ticket


def join_queue_walk_in(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    guest_name: str | None,
    guest_phone: str | None = None,
    guest_email: str | None = None,
    is_vip: bool = False,
) -> QueueEntry:
    svc = get_service_for_update(session, service_item_id)
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is not active")

    provider = session.get(Provider, svc.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # UC-13 (HIGH-1): pause halts *remote* joins only. The kiosk staff
    # still need to enrol walk-ins so the queue keeps reflecting reality
    # ("doctor on emergency break" + a walk-in arrives anyway). Closed
    # providers (``is_open == False``) genuinely refuse all joins.
    if not provider.is_open:
        raise HTTPException(
            status_code=400, detail="Provider is closed"
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
        guest_phone=guest_phone,
        guest_email=guest_email,
        priority=1 if is_vip else 0,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    from werefa.analytics.application.service import record_demand_event
    from werefa.shared.enums import DemandEventType

    record_demand_event(
        session,
        event_type=DemandEventType.join_walk_in,
        provider_id=provider.id,
        service_item_id=service_item_id,
        user_id=None,
        payload={"ticket_id": str(ticket.id)},
    )
    return ticket


def list_queue_entries(
    session: Session, service_item_id: uuid.UUID
) -> Sequence[QueueEntry]:
    statement = (
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .order_by(col(QueueEntry.priority).desc(), col(QueueEntry.joined_at))
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
        .order_by(col(QueueEntry.priority).desc(), col(QueueEntry.joined_at))
    ).first()

    if not nxt:
        session.commit()
        if current is not None:
            session.refresh(current)
        return current, None

    nxt.status = TicketStatus.serving.value
    # FR-06: stamp the moment we begin serving so the WMA can compute a real
    # serve duration on completion.
    nxt.serving_started_at = utcnow()
    session.add(nxt)
    session.commit()
    if current is not None:
        session.refresh(current)
    session.refresh(nxt)
    return current, nxt


def cancel_my_ticket(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    user: User,
) -> QueueEntry:
    """Customer-initiated cancel (CRIT-4).

    Differs from staff ``set_ticket_status(cancelled)`` in two ways:

    * Caller must be the ticket owner; staff cannot use this path.
    * **No strike is recorded** — FR-12 reserves the penalty for true
      no-shows (called but didn't appear). Voluntary leaves must stay
      free of charge or users will park indefinitely to dodge strikes.
    """
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.user_id is None or ticket.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel tickets that belong to you",
        )
    if ticket_rules.is_terminal_status(ticket.status):
        raise HTTPException(
            status_code=409,
            detail="This ticket is already in a terminal status",
        )
    if ticket.status == TicketStatus.pending_approval.value:
        pass
    elif ticket.status == TicketStatus.serving.value:
        # Once being served, only the provider should close the ticket
        # so they can pick the right terminal status (completed vs
        # no_show). Refuse the self-cancel.
        raise HTTPException(
            status_code=409,
            detail=(
                "You're being served — please ask the provider to close "
                "the ticket instead."
            ),
        )
    ticket.status = TicketStatus.cancelled.value
    ticket.completed_at = utcnow()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    from werefa.analytics.application.service import record_demand_event
    from werefa.shared.enums import DemandEventType

    svc = session.get(ServiceItem, ticket.service_item_id)
    record_demand_event(
        session,
        event_type=DemandEventType.queue_abandon,
        provider_id=svc.provider_id if svc else None,
        service_item_id=ticket.service_item_id,
        user_id=user.id,
        payload={"ticket_id": str(ticket.id)},
    )
    return ticket


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


def recall_last_completed(session: Session, service_item_id: uuid.UUID) -> QueueEntry:
    """FR-09: put the most recently completed ticket back to ``serving``.

    Guarded by a short wall-clock window, an empty serving slot, no review
    on the ticket, and the one-active-ticket partial unique index per user.
    """
    get_service_for_update(session, service_item_id)

    serving = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.serving.value)
    ).first()
    if serving is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Complete or no-show the current serving ticket before recalling "
                "the previous customer"
            ),
        )

    ticket = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.completed.value)
        .where(col(QueueEntry.completed_at).is_not(None))
        .order_by(col(QueueEntry.completed_at).desc())
    ).first()

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="No completed ticket available to recall",
        )

    try:
        ticket_rules.assert_recall_completed_allowed(
            completed_at=ticket.completed_at,
            now=utcnow(),
            window_seconds=settings.RECALL_COMPLETED_WINDOW_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    reviewed = session.exec(
        select(Review.id).where(Review.ticket_id == ticket.id)
    ).first()
    if reviewed is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot recall a ticket that already has a review",
        )

    ticket.status = TicketStatus.serving.value
    ticket.completed_at = None
    ticket.serving_started_at = utcnow()
    session.add(ticket)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        if _is_one_active_user_unique_violation(err):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "That customer already holds another active ticket; "
                    "recall is not possible"
                ),
            ) from None
        raise
    session.refresh(ticket)
    return ticket


def set_ticket_priority(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    priority: int,
) -> QueueEntry:
    """Staff can manually set VIP (priority=1) or remove it (priority=0)."""
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status not in (TicketStatus.waiting.value, TicketStatus.serving.value):
        raise HTTPException(
            status_code=400, detail="Can only change priority on active tickets"
        )
    ticket.priority = priority
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket
