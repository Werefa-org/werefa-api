"""FR-02: time-boxed join invites / QR deep links."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlmodel import Session, select

from werefa.shared.models import JoinInvite, utcnow


def create_invite(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    ttl_hours: int,
) -> JoinInvite:
    token = secrets.token_urlsafe(32)
    row = JoinInvite(
        token=token,
        service_item_id=service_item_id,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def resolve_invite(session: Session, *, token: str) -> JoinInvite:
    row = session.exec(
        select(JoinInvite).where(JoinInvite.token == token)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if row.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Invite revoked")
    if row.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")
    return row


def assert_invite_valid_for_service(
    session: Session,
    *,
    token: str | None,
    service_item_id: uuid.UUID,
) -> bool:
    """Return True when the token is valid for this service line."""
    if not token:
        return False
    inv = session.exec(
        select(JoinInvite).where(JoinInvite.token == token)
    ).first()
    if inv is None:
        return False
    if inv.service_item_id != service_item_id:
        return False
    if inv.revoked_at is not None or inv.expires_at <= utcnow():
        return False
    return True
