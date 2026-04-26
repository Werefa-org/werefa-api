"""FR-05 / Phase 11: top-K liveness sync + position pings."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.notifications.notifier import NotificationPayload
from werefa.shared.enums import LivenessState, NotificationKind, TicketSource, TicketStatus
from werefa.shared.models import PositionPing, QueueEntry, User, utcnow


def _line_position(session: Session, ticket: QueueEntry) -> int:
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
    raw = session.exec(statement).one()
    if isinstance(raw, tuple):
        raw = raw[0]
    return int(raw or 0)


def sync_liveness_for_service_line(
    session: Session, service_item_id: uuid.UUID
) -> bool:
    """Advance liveness states for remote waiting tickets in top-K.

    Returns ``True`` when any row or ledger mutation occurred so callers
    know to commit.
    """
    from werefa.notifications.application import service as notifications_service

    if not settings.LIVENESS_ENABLED:
        return False
    now = utcnow()
    dirty = False
    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(col(QueueEntry.user_id).is_not(None))
        .order_by(col(QueueEntry.ticket_number))
    ).all()

    for ticket in rows:
        if ticket.status != TicketStatus.waiting.value:
            if ticket.liveness_state != LivenessState.idle.value:
                ticket.liveness_state = LivenessState.idle.value
                ticket.liveness_deadline_at = None
                session.add(ticket)
                dirty = True
            continue

        if ticket.source not in (
            TicketSource.remote_app.value,
            TicketSource.qr_scan.value,
        ):
            continue

        pos = _line_position(session, ticket)
        if pos > settings.LIVENESS_TOP_K:
            if ticket.liveness_state != LivenessState.idle.value:
                ticket.liveness_state = LivenessState.idle.value
                ticket.liveness_deadline_at = None
                session.add(ticket)
                dirty = True
            continue

        if ticket.liveness_state == LivenessState.idle.value:
            ticket.liveness_state = LivenessState.awaiting.value
            ticket.liveness_deadline_at = now + timedelta(
                seconds=settings.LIVENESS_GRACE_SECONDS
            )
            session.add(ticket)
            user = session.get(User, ticket.user_id)
            if user is not None:
                notifications_service.dispatch(
                    session,
                    user=user,
                    payload=NotificationPayload(
                        kind=NotificationKind.liveness_ping_request,
                        body=(
                            "You're near the front of the line — share your location "
                            "to show you're on the way."
                        ),
                        ticket_id=ticket.id,
                        service_item_id=service_item_id,
                        position=pos,
                    ),
                )
            dirty = True
        elif ticket.liveness_state in (
            LivenessState.awaiting.value,
            LivenessState.ok.value,
        ):
            if (
                ticket.liveness_deadline_at is not None
                and now >= ticket.liveness_deadline_at
            ):
                ticket.liveness_state = LivenessState.flagged.value
                session.add(ticket)
                user = session.get(User, ticket.user_id)
                if user is not None:
                    notifications_service.dispatch(
                        session,
                        user=user,
                        payload=NotificationPayload(
                            kind=NotificationKind.liveness_stale,
                            body=(
                                "We have not received a recent location update. "
                                "Open your ticket and share your location so you "
                                "do not lose your spot."
                            ),
                            ticket_id=ticket.id,
                            service_item_id=service_item_id,
                            position=pos,
                        ),
                    )
                dirty = True

    return dirty


def record_position_ping(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    user: User,
    latitude: float,
    longitude: float,
    accuracy_m: int | None,
) -> QueueEntry:
    ticket = session.get(QueueEntry, ticket_id)
    if (
        ticket is None
        or ticket.service_item_id != service_item_id
        or ticket.user_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != TicketStatus.waiting.value:
        raise HTTPException(
            status_code=400,
            detail="Position pings are only accepted for waiting tickets",
        )
    if ticket.source not in (
        TicketSource.remote_app.value,
        TicketSource.qr_scan.value,
    ):
        raise HTTPException(
            status_code=400,
            detail="Walk-in tickets do not use remote liveness pings",
        )

    row = PositionPing(
        ticket_id=ticket.id,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
    )
    session.add(row)
    ticket.liveness_state = LivenessState.ok.value
    ticket.liveness_deadline_at = utcnow() + timedelta(
        seconds=settings.LIVENESS_GRACE_SECONDS
    )
    session.add(ticket)
    session.commit()
    session.refresh(row)
    session.refresh(ticket)
    return ticket


def read_liveness(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
) -> tuple[QueueEntry, PositionPing | None]:
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    touched = sync_liveness_for_service_line(session, ticket.service_item_id)
    if touched:
        session.commit()
    session.refresh(ticket)

    last = session.exec(
        select(PositionPing)
        .where(PositionPing.ticket_id == ticket_id)
        .order_by(col(PositionPing.sent_at).desc())
    ).first()
    return ticket, last
