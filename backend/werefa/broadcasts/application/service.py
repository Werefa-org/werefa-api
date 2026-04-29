"""Provider broadcast service (FR-08, UC-11).

Validation, idempotency, persistence, *and* realtime fan-out all live
here so the router stays thin. The realtime call is best-effort: a
publish failure doesn't roll back the saved row — the message is in the
ledger and ``GET /providers/{id}/broadcasts`` will still serve it.
"""

import logging
import uuid
from datetime import datetime
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from werefa.broadcasts.infrastructure import repo as broadcasts_repo
from werefa.realtime.notify import notify_broadcast_subscribers
from werefa.shared.enums import BroadcastSeverity
from werefa.shared.models import (
    BroadcastCreate,
    BroadcastMessage,
    Provider,
    ServiceItem,
)

logger = logging.getLogger(__name__)


def _validate_severity(value: str) -> str:
    valid = {s.value for s in BroadcastSeverity}
    if value not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"severity must be one of {sorted(valid)}",
        )
    return value


def _ensure_service_belongs_to_provider(
    session: Session,
    *,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
) -> ServiceItem:
    svc = session.get(ServiceItem, service_item_id)
    if svc is None or svc.provider_id != provider_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service line not found for this provider",
        )
    return svc


def create_broadcast(
    session: Session,
    *,
    provider_id: uuid.UUID,
    author_user_id: uuid.UUID,
    body: BroadcastCreate,
) -> tuple[BroadcastMessage, bool]:
    """Persist + fan out a new broadcast.

    Returns ``(record, created)``. ``created=False`` means the request
    matched a previous one by ``idempotency_key`` and the existing record
    is being returned without re-publishing the realtime event.
    """
    if session.get(Provider, provider_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    severity = _validate_severity(body.severity)

    if body.service_item_id is not None:
        _ensure_service_belongs_to_provider(
            session, provider_id=provider_id, service_item_id=body.service_item_id
        )

    if body.idempotency_key is not None:
        existing = broadcasts_repo.get_by_idempotency_key(
            session=session,
            provider_id=provider_id,
            idempotency_key=body.idempotency_key,
        )
        if existing is not None:
            return existing, False

    row = BroadcastMessage(
        provider_id=provider_id,
        service_item_id=body.service_item_id,
        author_user_id=author_user_id,
        body=body.body,
        severity=severity,
        idempotency_key=body.idempotency_key,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as err:
        # Two parallel requests with the same idempotency_key: the unique
        # constraint resolved the race, return the winner.
        session.rollback()
        if body.idempotency_key is not None:
            existing = broadcasts_repo.get_by_idempotency_key(
                session=session,
                provider_id=provider_id,
                idempotency_key=body.idempotency_key,
            )
            if existing is not None:
                return existing, False
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not persist broadcast",
        ) from err
    session.refresh(row)

    logger.info(
        "broadcast_created",
        extra={
            "broadcast_id": str(row.id),
            "provider_id": str(provider_id),
            "service_item_id": (
                str(row.service_item_id) if row.service_item_id else None
            ),
            "severity": severity,
            "idempotent": body.idempotency_key is not None,
        },
    )

    # Fan-out: when a service_item is named, publish only on that channel;
    # otherwise iterate every service line of the provider.
    target_service_items: list[uuid.UUID]
    if row.service_item_id is not None:
        target_service_items = [row.service_item_id]
    else:
        rows = session.exec(
            select(ServiceItem.id).where(ServiceItem.provider_id == provider_id)
        ).all()
        target_service_items = [cast(uuid.UUID, sid) for sid in rows]

    notify_broadcast_subscribers(
        broadcast_id=row.id,
        provider_id=provider_id,
        body_text=row.body,
        severity=severity,
        # `target_service_items` reflects what the realtime layer will see;
        # the persisted record retains the original `service_item_id` (None
        # when provider-wide) so historical queries remain truthful.
        service_item_ids=target_service_items,
        original_service_item_id=row.service_item_id,
    )
    return row, True


def list_for_provider(
    session: Session,
    *,
    provider_id: uuid.UUID,
    since: datetime | None,
    limit: int,
) -> list[BroadcastMessage]:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    rows = broadcasts_repo.list_for_provider(
        session=session,
        provider_id=provider_id,
        since=since,
        limit=limit,
    )
    return list(rows)
