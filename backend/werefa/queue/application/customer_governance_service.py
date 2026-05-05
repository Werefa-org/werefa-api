"""Provider customer directory, bans, and join approvals."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application.service import get_service_for_update
from werefa.shared.enums import ApprovalQueueOrder, TicketStatus
from werefa.shared.models import (
    Provider,
    ProviderCustomerBlock,
    ProviderCustomerPublic,
    ProviderCustomersPublic,
    QueueEntry,
    ServiceItem,
    User,
    utcnow,
)


def _blocked_user_ids(session: Session, provider_id: uuid.UUID) -> set[uuid.UUID]:
    rows = session.exec(
        select(ProviderCustomerBlock.user_id).where(
            ProviderCustomerBlock.provider_id == provider_id
        )
    ).all()
    return set(rows)


def assert_not_banned(
    session: Session, *, provider_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    row = session.exec(
        select(ProviderCustomerBlock.id).where(
            ProviderCustomerBlock.provider_id == provider_id,
            ProviderCustomerBlock.user_id == user_id,
        )
    ).first()
    if row is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to join this queue",
        )


def list_provider_customers(
    session: Session,
    *,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID | None = None,
) -> ProviderCustomersPublic:
    svc_ids_stmt = select(ServiceItem.id).where(ServiceItem.provider_id == provider_id)
    if service_item_id is not None:
        svc_ids_stmt = svc_ids_stmt.where(ServiceItem.id == service_item_id)
    service_ids = list(session.exec(svc_ids_stmt).all())
    if not service_ids:
        return ProviderCustomersPublic(data=[], count=0)

    tickets = list(
        session.exec(
            select(QueueEntry)
            .where(col(QueueEntry.service_item_id).in_(service_ids))
            .where(col(QueueEntry.user_id).is_not(None))
            .order_by(col(QueueEntry.joined_at).desc())
        ).all()
    )

    blocked = _blocked_user_ids(session, provider_id)
    by_user: dict[uuid.UUID, dict] = defaultdict(
        lambda: {
            "ticket_count": 0,
            "last_joined_at": None,
            "has_active_ticket": False,
        }
    )
    user_ids: set[uuid.UUID] = set(blocked)
    active_statuses = {
        TicketStatus.waiting.value,
        TicketStatus.serving.value,
        TicketStatus.pending_approval.value,
    }

    for t in tickets:
        if t.user_id is None:
            continue
        uid = t.user_id
        user_ids.add(uid)
        rec = by_user[uid]
        rec["ticket_count"] += 1
        if t.joined_at and (
            rec["last_joined_at"] is None or t.joined_at > rec["last_joined_at"]
        ):
            rec["last_joined_at"] = t.joined_at
        if t.status in active_statuses:
            rec["has_active_ticket"] = True

    users = {
        u.id: u
        for u in session.exec(select(User).where(col(User.id).in_(list(user_ids)))).all()
    }
    if not user_ids:
        return ProviderCustomersPublic(data=[], count=0)

    data: list[ProviderCustomerPublic] = []
    for uid in user_ids:
        u = users.get(uid)
        meta = by_user[uid]
        data.append(
            ProviderCustomerPublic(
                user_id=uid,
                full_name=u.full_name if u else None,
                email=str(u.email) if u else None,
                phone_number=u.phone_number if u else None,
                is_banned=uid in blocked,
                ticket_count=meta["ticket_count"],
                last_joined_at=meta["last_joined_at"],
                has_active_ticket=meta["has_active_ticket"],
            )
        )
    data.sort(
        key=lambda row: (
            0 if row.has_active_ticket else 1,
            -(row.last_joined_at.timestamp() if row.last_joined_at else 0),
        )
    )
    return ProviderCustomersPublic(data=data, count=len(data))


def ban_customer(
    session: Session,
    *,
    provider_id: uuid.UUID,
    user_id: uuid.UUID,
    blocked_by_user_id: uuid.UUID,
    reason: str | None,
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = session.exec(
        select(ProviderCustomerBlock).where(
            ProviderCustomerBlock.provider_id == provider_id,
            ProviderCustomerBlock.user_id == user_id,
        )
    ).first()
    if existing is None:
        session.add(
            ProviderCustomerBlock(
                provider_id=provider_id,
                user_id=user_id,
                blocked_by_user_id=blocked_by_user_id,
                reason=reason,
            )
        )

    service_ids = list(
        session.exec(
            select(ServiceItem.id).where(ServiceItem.provider_id == provider_id)
        ).all()
    )
    if service_ids:
        active = session.exec(
            select(QueueEntry).where(
                col(QueueEntry.service_item_id).in_(service_ids),
                QueueEntry.user_id == user_id,
                col(QueueEntry.status).in_(
                    (
                        TicketStatus.waiting.value,
                        TicketStatus.serving.value,
                        TicketStatus.pending_approval.value,
                    )
                ),
            )
        ).all()
        now = utcnow()
        for ticket in active:
            ticket.status = TicketStatus.cancelled.value
            ticket.completed_at = now
            ticket.close_reason = "customer_banned"
            session.add(ticket)
    session.commit()


def unban_customer(
    session: Session, *, provider_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    row = session.exec(
        select(ProviderCustomerBlock).where(
            ProviderCustomerBlock.provider_id == provider_id,
            ProviderCustomerBlock.user_id == user_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="User is not banned")
    session.delete(row)
    session.commit()


def approve_ticket(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    approver: User,
    queue_order: ApprovalQueueOrder | None = None,
) -> QueueEntry:
    get_service_for_update(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != TicketStatus.pending_approval.value:
        raise HTTPException(status_code=409, detail="Ticket is not awaiting approval")

    svc = session.get(ServiceItem, service_item_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")

    order = queue_order or ApprovalQueueOrder(svc.approval_queue_order)
    now = utcnow()
    if order == ApprovalQueueOrder.approval_time:
        ticket.joined_at = now

    ticket.status = TicketStatus.waiting.value
    ticket.approved_at = now
    ticket.approved_by_user_id = approver.id
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def reject_ticket(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
) -> QueueEntry:
    get_service_for_update(session, service_item_id)
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status != TicketStatus.pending_approval.value:
        raise HTTPException(status_code=409, detail="Ticket is not awaiting approval")

    ticket.status = TicketStatus.cancelled.value
    ticket.completed_at = utcnow()
    ticket.close_reason = "join_rejected"
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket
