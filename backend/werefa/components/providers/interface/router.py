import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    SuperUser,
    ensure_provider_owner_or_super,
    ensure_provider_staff,
)
from werefa.components.providers.application import service as provider_service
from werefa.models import (
    MembershipCreate,
    MembershipPublic,
    ProviderCreate,
    ProviderPublic,
    ProviderUpdate,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/", response_model=ProviderPublic)
def create_provider(
    *, session: SessionDep, _admin: SuperUser, body: ProviderCreate
) -> Any:
    return provider_service.create_provider(session, body)


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
