"""Persistence for provider broadcasts (FR-08).

The repo is intentionally thin — service-side rules (severity validation,
idempotency, fan-out) live in the application layer.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session, col, select

from werefa.shared.models import BroadcastMessage


def get_by_idempotency_key(
    *,
    session: Session,
    provider_id: uuid.UUID,
    idempotency_key: str,
) -> BroadcastMessage | None:
    statement = (
        select(BroadcastMessage)
        .where(BroadcastMessage.provider_id == provider_id)
        .where(BroadcastMessage.idempotency_key == idempotency_key)
    )
    return session.exec(statement).first()


def list_for_provider(
    *,
    session: Session,
    provider_id: uuid.UUID,
    since: datetime | None,
    limit: int,
) -> Sequence[BroadcastMessage]:
    statement = select(BroadcastMessage).where(
        BroadcastMessage.provider_id == provider_id
    )
    if since is not None:
        statement = statement.where(col(BroadcastMessage.created_at) >= since)
    statement = (
        statement.order_by(col(BroadcastMessage.created_at).desc()).limit(limit)
    )
    return session.exec(statement).all()
