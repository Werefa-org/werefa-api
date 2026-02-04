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
    # Reads are restricted to staff/owner because the message is
    # operational ("doctor running 20 min late") and could leak business
    # state if exposed to anyone.
    try:
        ensure_provider_staff(
            session=session, current_user=current_user, provider_id=provider_id
        )
    except HTTPException:
        raise
    rows = broadcasts_service.list_for_provider(
        session, provider_id=provider_id, since=since, limit=limit
    )
    return BroadcastsPublic(
        data=[BroadcastPublic.model_validate(r) for r in rows], count=len(rows)
    )
