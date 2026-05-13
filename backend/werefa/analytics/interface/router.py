"""Public demand capture + admin aggregates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from werefa.analytics.application import service as analytics_service
from werefa.api.deps import SessionDep, SuperUser, get_optional_current_user
from werefa.shared.enums import DemandEventType
from werefa.shared.models import DemandEventIngest, User

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin/analytics", tags=["admin"])


@router.post("/demand-events", status_code=status.HTTP_201_CREATED)
def ingest_demand_event(
    *,
    session: SessionDep,
    body: DemandEventIngest,
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> dict[str, str]:
    """Light-weight funnel logging (views, optional client-side signals).

    Anonymous callers may omit auth; authenticated callers get ``user_id``
    stamped automatically.
    """
    if body.event_type not in {e.value for e in DemandEventType}:
        valid = ", ".join(sorted(x.value for x in DemandEventType))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event_type. Expected one of: {valid}",
        )
    analytics_service.record_demand_event(
        session,
        event_type=body.event_type,
        provider_id=body.provider_id,
        service_item_id=body.service_item_id,
        user_id=current_user.id if current_user else None,
        client_ref=body.client_ref,
        payload=body.payload,
    )
    return {"status": "recorded"}


@admin_router.get("/demand-summary")
def admin_demand_summary(
    *,
    session: SessionDep,
    _admin: SuperUser,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> dict[str, Any]:
    pairs = analytics_service.demand_summary(session, since=since, until=until)
    return {"data": [{"event_type": k, "count": v} for k, v in pairs]}


@admin_router.get("/demand.csv")
def admin_demand_csv(
    *,
    session: SessionDep,
    _admin: SuperUser,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> Response:
    text = analytics_service.demand_events_csv(session, since=since, until=until)
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="demand_events.csv"'},
    )
