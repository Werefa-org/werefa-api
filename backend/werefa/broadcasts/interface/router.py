"""HTTP surface for provider broadcasts (FR-08, UC-11)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    ensure_provider_staff,
)
from werefa.broadcasts.application import service as broadcasts_service
from werefa.providers.infrastructure import repo as provider_repo
from werefa.shared.models import (
    BroadcastCreate,
    BroadcastPublic,
    BroadcastsPublic,
)

router = APIRouter(prefix="/providers", tags=["broadcasts"])


@router.post(
    "/{provider_id}/broadcasts",
    response_model=BroadcastPublic,
    status_code=status.HTTP_201_CREATED,
)
def post_broadcast(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: BroadcastCreate,
    response: Response,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    record, created = broadcasts_service.create_broadcast(
        session,
        provider_id=provider_id,
        author_user_id=current_user.id,
        body=body,
    )
    if not created:
        # Idempotent replay: surface 200 so the client can distinguish a
        # fresh publish from a deduped retry without needing to read the
        # response body.
        response.status_code = status.HTTP_200_OK
    return record


@router.get(
    "/{provider_id}/broadcasts",
    response_model=BroadcastsPublic,
)
def list_broadcasts(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    since: datetime | None = Query(
        default=None,
        description=(
            "ISO-8601 timestamp; only broadcasts with `created_at >= since` "
            "are returned. Use the previous response's most-recent "
            "`created_at` to page forward."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """List broadcasts for a provider.

    * **Staff / owner / admin** receive every broadcast for the provider
      (operational messages targeted at any service line).
    * **Customers** with an active (waiting/serving) ticket on the
      provider receive only the broadcasts that fan out to *their*
      lines — both provider-wide messages and service-scoped ones for
      the lines they're on. This is the REST counterpart to the
      ``broadcast_v1`` events on the ticket WebSocket so a brief drop
      doesn't lose them messages (CRIT-5).
    * **Anyone else** gets 403.
    """
    is_staff = current_user.is_superuser or (
        provider_repo.get_membership(
            session=session, provider_id=provider_id, user_id=current_user.id
        )
        is not None
    )
    if is_staff:
        rows = broadcasts_service.list_for_provider(
            session, provider_id=provider_id, since=since, limit=limit
        )
        return BroadcastsPublic(
            data=[BroadcastPublic.model_validate(r) for r in rows],
            count=len(rows),
        )

    service_item_ids = broadcasts_service.active_service_item_ids_for_user(
        session, provider_id=provider_id, user=current_user
    )
    if not service_item_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Broadcasts are visible to staff or to customers with an "
                "active ticket on this provider."
            ),
        )
    rows = broadcasts_service.list_for_provider(
        session,
        provider_id=provider_id,
        since=since,
        limit=limit,
        service_item_ids=service_item_ids,
    )
    return BroadcastsPublic(
        data=[BroadcastPublic.model_validate(r) for r in rows], count=len(rows)
    )
