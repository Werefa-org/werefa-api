"""FR-02: public resolution of QR / deep-link tokens."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from werefa.api.deps import SessionDep
from werefa.queue.application import join_invite_service
from werefa.shared.models import JoinInviteResolved, Provider, ServiceItem

router = APIRouter(prefix="/join-invites", tags=["join-invites"])


@router.get("/resolve", response_model=JoinInviteResolved)
def resolve_join_invite(
    *,
    session: SessionDep,
    token: str = Query(..., min_length=8, max_length=80),
) -> Any:
    inv = join_invite_service.resolve_invite(session, token=token)
    svc = session.get(ServiceItem, inv.service_item_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    p = session.get(Provider, svc.provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return JoinInviteResolved(
        service_item_id=inv.service_item_id,
        provider_id=p.id,
        slug=p.slug,
        biz_name=p.biz_name,
    )
