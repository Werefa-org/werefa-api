"""Per-line group chat for waiting customers and provider staff."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from werefa.api.deps import ensure_provider_staff
from werefa.providers.infrastructure import repo as provider_repo
from werefa.realtime.notify import notify_line_chat_subscribers
from werefa.shared.enums import MembershipRole, TicketStatus
from werefa.shared.models import (
    LineChatCreate,
    LineChatMessage,
    LineChatMessagePublic,
    Provider,
    QueueEntry,
    ServiceItem,
    User,
)


def _author_role_and_label(
    session: Session,
    *,
    provider_id: uuid.UUID,
    author: User,
) -> tuple[str, str]:
    provider = session.get(Provider, provider_id)
    biz = (provider.biz_name if provider else None) or "Business"
    membership = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=author.id
    )
    if membership is not None and membership.role == MembershipRole.owner.value:
        return MembershipRole.owner.value, biz
    if membership is not None:
        return MembershipRole.staff.value, f"{biz} team"
    label = (author.full_name or "").strip() or "Customer"
    return "seeker", label


def _has_active_ticket(
    session: Session, *, service_item_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    row = session.exec(
        select(QueueEntry.id)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.user_id == user_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
    ).first()
    return row is not None


def _is_staff(session: Session, *, provider_id: uuid.UUID, user: User) -> bool:
    if user.is_superuser:
        return True
    return (
        provider_repo.get_membership(
            session=session, provider_id=provider_id, user_id=user.id
        )
        is not None
    )


def to_line_chat_public(
    session: Session, row: LineChatMessage, *, provider_id: uuid.UUID
) -> LineChatMessagePublic:
    author = session.get(User, row.author_user_id)
    if author is None:
        role, label = "seeker", "Guest"
    else:
        role, label = _author_role_and_label(
            session, provider_id=provider_id, author=author
        )
    base = LineChatMessagePublic.model_validate(row)
    return base.model_copy(update={"author_role": role, "author_label": label})


def list_messages(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    user: User,
    limit: int = 100,
) -> tuple[list[LineChatMessagePublic], bool]:
    svc = session.get(ServiceItem, service_item_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    if not _is_staff(session, provider_id=svc.provider_id, user=user):
        if not _has_active_ticket(
            session, service_item_id=service_item_id, user_id=user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Line chat is only available with an active ticket on this line.",
            )
    statement = select(LineChatMessage).where(
        LineChatMessage.service_item_id == service_item_id
    )
    if svc.line_chat_cleared_at is not None:
        statement = statement.where(
            col(LineChatMessage.created_at) > svc.line_chat_cleared_at
        )
    rows = session.exec(
        statement.order_by(col(LineChatMessage.created_at)).limit(limit)
    ).all()
    data = [to_line_chat_public(session, r, provider_id=svc.provider_id) for r in rows]
    return data, svc.line_chat_enabled


def post_message(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    user: User,
    body: LineChatCreate,
) -> LineChatMessagePublic:
    svc = session.get(ServiceItem, service_item_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    if not svc.line_chat_enabled:
        raise HTTPException(
            status_code=403,
            detail="Line chat is disabled for this queue.",
        )
    staff = _is_staff(session, provider_id=svc.provider_id, user=user)
    if not staff:
        if not _has_active_ticket(
            session, service_item_id=service_item_id, user_id=user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="You need an active ticket on this line to chat.",
            )
    row = LineChatMessage(
        service_item_id=service_item_id,
        author_user_id=user.id,
        body=body.body.strip(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    public = to_line_chat_public(session, row, provider_id=svc.provider_id)
    notify_line_chat_subscribers(
        message_id=row.id,
        service_item_id=service_item_id,
        body_text=row.body,
        author_role=public.author_role,
        author_label=public.author_label,
        author_user_id=user.id,
    )
    if staff:
        from werefa.notifications.application import service as notifications_service

        notifications_service.notify_line_chat_staff_message(
            session,
            service_item_id=service_item_id,
            body_text=row.body,
            author_label=public.author_label,
            author_user_id=user.id,
        )
    return public


def set_line_chat_enabled(
    session: Session,
    *,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
    user: User,
    enabled: bool,
) -> ServiceItem:
    ensure_provider_staff(
        session=session, current_user=user, provider_id=provider_id
    )
    membership = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=user.id
    )
    if not user.is_superuser and (
        membership is None or membership.role != MembershipRole.owner.value
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the business owner can change line chat settings.",
        )
    svc = session.get(ServiceItem, service_item_id)
    if svc is None or svc.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Service not found")
    svc.line_chat_enabled = enabled
    session.add(svc)
    session.commit()
    session.refresh(svc)
    return svc
