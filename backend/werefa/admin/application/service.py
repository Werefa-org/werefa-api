"""Admin governance helpers (UC-16)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from werefa.shared.models import AdminAuditLog, User, utcnow


def log_admin_action(
    session: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    details: dict | None = None,
) -> None:
    row = AdminAuditLog(
        actor_user_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    session.add(row)


def suspend_user(
    session: Session,
    *,
    target_id: uuid.UUID,
    actor: User,
    reason: str,
) -> User:
    if target_id == actor.id:
        raise HTTPException(
            status_code=400,
            detail="Administrators cannot suspend themselves",
        )
    user = session.get(User, target_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_suspended = True
    user.suspended_at = utcnow()
    user.suspended_reason = reason
    session.add(user)
    log_admin_action(
        session,
        actor=actor,
        action="user.suspend",
        entity_type="user",
        entity_id=target_id,
        details={"reason": reason},
    )
    session.commit()
    session.refresh(user)
    return user


def unsuspend_user(session: Session, *, target_id: uuid.UUID, actor: User) -> User:
    user = session.get(User, target_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_suspended = False
    user.suspended_at = None
    user.suspended_reason = None
    session.add(user)
    log_admin_action(
        session,
        actor=actor,
        action="user.unsuspend",
        entity_type="user",
        entity_id=target_id,
        details=None,
    )
    session.commit()
    session.refresh(user)
    return user


def search_users_by_phone(
    session: Session, *, q: str, limit: int = 20
) -> list[User]:
    if len(q) < 3:
        raise HTTPException(
            status_code=400,
            detail="Search string must be at least 3 characters",
        )
    like = f"%{q}%"
    statement = (
        select(User)
        .where(col(User.phone_number).is_not(None))
        .where(col(User.phone_number).like(like))
        .limit(limit)
    )
    return list(session.exec(statement).all())
