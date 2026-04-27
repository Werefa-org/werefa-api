import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    ensure_provider_owner_or_super,
    ensure_provider_staff,
)
from werefa.providers.application import service as provider_service
from werefa.shared.enums import UserType
from werefa.shared.models import (
    MembershipCreate,
    MembershipPublic,
    ProviderCreate,
    ProviderDiscoveriesPublic,
    ProviderPublic,
    ProviderUpdate,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/discover", response_model=ProviderDiscoveriesPublic)
def discover_providers(
    *,
    session: SessionDep,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: int | None = Query(default=None, ge=1),
    query: str | None = Query(default=None, min_length=1, max_length=120),
    include_private: bool = False,
    only_open: bool = True,
    include_paused: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return provider_service.discover_providers(
        session,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        query=query,
        include_private=include_private,
        only_open=only_open,
        include_paused=include_paused,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=ProviderPublic)
def create_provider(
    *, session: SessionDep, current_user: CurrentUser, body: ProviderCreate
) -> Any:
    if current_user.is_superuser:
        effective = body
    elif current_user.user_type == UserType.provider.value:
        owner_id = (
            body.owner_user_id
            if body.owner_user_id is not None
            else current_user.id
        )
        if owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Provider accounts can only create businesses they will own "
                    "themselves"
                ),
            )
        effective = body.model_copy(update={"owner_user_id": current_user.id})
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only provider or administrator accounts can create a business",
        )
    return provider_service.create_provider(session, effective)


@router.get("/by-slug/{slug}", response_model=ProviderPublic)
def read_provider_by_slug(*, session: SessionDep, slug: str) -> Any:
    p = provider_service.get_provider_by_slug(session, slug)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p


@router.get("/{provider_id}", response_model=ProviderPublic)
def read_provider(*, session: SessionDep, provider_id: uuid.UUID) -> Any:
    p = provider_service.get_provider(session, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p


@router.patch("/{provider_id}", response_model=ProviderPublic)
def update_provider(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: ProviderUpdate,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return provider_service.update_provider(session, provider_id, body)


@router.post("/{provider_id}/members", response_model=MembershipPublic)
def add_provider_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: MembershipCreate,
) -> Any:
    ensure_provider_owner_or_super(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return provider_service.add_provider_member(session, provider_id, body)


@router.get("/{provider_id}/members", response_model=list[MembershipPublic])
def list_provider_members(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return provider_service.list_provider_members(session, provider_id)


@router.delete(
    "/{provider_id}/members/{member_user_id}", response_model=MembershipPublic
)
def remove_provider_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    member_user_id: uuid.UUID,
) -> Any:
    ensure_provider_owner_or_super(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return provider_service.remove_provider_member(session, provider_id, member_user_id)
