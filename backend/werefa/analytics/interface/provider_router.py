"""Provider analytics (staff/owner)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query

from werefa.analytics.application import provider_analytics_service
from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.shared.models import ProviderAnalyticsPublic

router = APIRouter(prefix="/providers", tags=["analytics"])


@router.get("/{provider_id}/analytics", response_model=ProviderAnalyticsPublic)
def provider_analytics(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=90),
    service_item_id: uuid.UUID | None = Query(default=None),
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return provider_analytics_service.build_provider_analytics(
        session,
        provider_id=provider_id,
        service_item_id=service_item_id,
        days=days,
    )
