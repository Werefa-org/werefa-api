import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    SuperUser,
    ensure_provider_owner_or_super,
    ensure_provider_staff,
    get_optional_current_user,
)
from werefa.providers.application import service as provider_service
from werefa.providers.application.service import provider_public_view
from werefa.shared.enums import UserType
from werefa.shared.models import (
    MembershipCreate,
    MembershipPublic,
    ProviderCreate,
    ProviderDiscoveriesPublic,
    ProviderPublic,
    ProviderStaffPublic,
    ProviderUpdate,
    User,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/discover", response_model=ProviderDiscoveriesPublic)
def discover_providers(
    *,
    session: SessionDep,
    current_user: User | None = Depends(get_optional_current_user),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: int | None = Query(default=None, ge=1),
    query: str | None = Query(default=None, min_length=1, max_length=120),
    include_private: bool = False,
    only_open: bool = True,
    include_paused: bool = False,
    include_unverified: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    # Privacy gates: ``include_private`` and ``include_unverified`` are
    # admin-only escape hatches. For everyone else we silently coerce
    # them off so the surface stays safe even on URL tampering.
    is_admin = current_user is not None and current_user.is_superuser
    if not is_admin:
        include_private = False
        include_unverified = False
    return provider_service.discover_providers(
        session,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        query=query,
        include_private=include_private,
        only_open=only_open,
        include_paused=include_paused,
        include_unverified=include_unverified,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=ProviderPublic)
def create_provider(
    *, session: SessionDep, current_user: CurrentUser, body: ProviderCreate
) -> Any:
    if current_user.is_superuser:
        effective = body
        if effective.owner_user_id is None:
            # Default the owner to the admin who created it; this stops
            # us ever persisting a provider with no manageable owner
            # membership (HIGH-2).
            effective = effective.model_copy(
                update={"owner_user_id": current_user.id}
            )
        auto_verify = True
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
        # Self-signups stay in `pending` until admin verifies (UC-10).
        auto_verify = False
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only provider or administrator accounts can create a business",
        )
    p = provider_service.create_provider(
        session, effective, auto_verify=auto_verify
    )
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@router.get(
    "/{provider_id}/access-code",
    response_model=ProviderStaffPublic,
)
def read_provider_access_code(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    """Staff-only read of the rotating access code (CRIT-1).

    The public ``ProviderPublic`` payload deliberately omits the code so
    third parties can't fetch it via ``GET /providers/{id}``. Owners and
    staff retrieve it through this dedicated endpoint instead.
    """
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    p = provider_service.get_provider(session, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderStaffPublic.model_validate(p, update=provider_public_view(p))


@router.get("/by-slug/{slug}", response_model=ProviderPublic)
def read_provider_by_slug(*, session: SessionDep, slug: str) -> Any:
    p = provider_service.get_provider_by_slug(session, slug)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@router.get("/{provider_id}", response_model=ProviderPublic)
def read_provider(*, session: SessionDep, provider_id: uuid.UUID) -> Any:
    p = provider_service.get_provider(session, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


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
    p = provider_service.update_provider(session, provider_id, body)
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


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


admin_router = APIRouter(prefix="/admin/providers", tags=["admin"])


@admin_router.post("/{provider_id}/verify", response_model=ProviderPublic)
def admin_verify_provider(
    *,
    session: SessionDep,
    _admin: SuperUser,
    provider_id: uuid.UUID,
) -> Any:
    """Admin (UC-10) flips a pending provider to ``verified`` so it
    appears in public discovery."""
    p = provider_service.admin_verify_provider(session, provider_id)
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@admin_router.post("/{provider_id}/reject", response_model=ProviderPublic)
def admin_reject_provider(
    *,
    session: SessionDep,
    _admin: SuperUser,
    provider_id: uuid.UUID,
) -> Any:
    """Admin (UC-10) marks a provider as ``rejected`` — it stays out of
    public discovery and the owner sees the status on their dashboard."""
    p = provider_service.admin_reject_provider(session, provider_id)
    return ProviderPublic.model_validate(p, update=provider_public_view(p))
