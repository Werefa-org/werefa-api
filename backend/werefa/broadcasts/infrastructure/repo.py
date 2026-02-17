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
    service_item_ids: list[uuid.UUID] | None = None,
) -> Sequence[BroadcastMessage]:
    """List broadcast rows for a provider, newest first.

    ``service_item_ids`` constrains the query to provider-wide
    broadcasts (``service_item_id IS NULL``) plus broadcasts targeted at
    one of the supplied lines — used for the customer-facing read in
    CRIT-5 so a customer only sees broadcasts that actually fan out to
    their queue.
    """
    statement = select(BroadcastMessage).where(
        BroadcastMessage.provider_id == provider_id
    )
    if service_item_ids is not None:
        statement = statement.where(
            col(BroadcastMessage.service_item_id).is_(None)
            | col(BroadcastMessage.service_item_id).in_(service_item_ids)
        )
    if since is not None:
        statement = statement.where(col(BroadcastMessage.created_at) >= since)
    statement = (
        statement.order_by(col(BroadcastMessage.created_at).desc()).limit(limit)
    )
    return session.exec(statement).all()
