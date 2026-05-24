import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse

from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    SuperUser,
    ensure_provider_owner_or_super,
    ensure_provider_staff,
    get_optional_current_user,
)
from werefa.providers.application import documents_service, service as provider_service
from werefa.queue.application import customer_governance_service
from werefa.providers.application.service import provider_public_view
from werefa.shared.enums import UserType
from werefa.shared.models import (
    MembershipCreate,
    MembershipPublic,
    ProviderMemberPublic,
    MyProviderPublic,
    MyProvidersPublic,
    ProviderCreate,
    ProviderDiscoveriesPublic,
    DiscoveryCitiesPublic,
    ProviderDocument,
    ProviderDocumentPublic,
    ProviderPublic,
    ProviderRejectBody,
    ProviderStaffPublic,
    ProviderUpdate,
    ProviderBanCreate,
    ProviderCustomersPublic,
    User,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/discover/cities", response_model=DiscoveryCitiesPublic)
def list_discovery_cities(*, session: SessionDep) -> Any:
    cities = provider_service.list_discovery_cities(session)
    return DiscoveryCitiesPublic(data=cities, count=len(cities))


@router.get("/discover", response_model=ProviderDiscoveriesPublic)
def discover_providers(
    *,
    session: SessionDep,
    current_user: User | None = Depends(get_optional_current_user),
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: int | None = Query(default=None, ge=1),
    query: str | None = Query(default=None, min_length=1, max_length=120),
    city: str | None = Query(default=None, min_length=1, max_length=100),
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
        city=city,
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
    return ProviderStaffPublic.model_validate(
        p,
        update={
            **provider_public_view(p),
            "last_rejection_reason": p.last_rejection_reason,
        },
    )


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


@router.get("/{provider_id}/customers", response_model=ProviderCustomersPublic)
def list_provider_customers(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    return customer_governance_service.list_provider_customers(
        session, provider_id=provider_id
    )


@router.post("/{provider_id}/customers/ban", status_code=status.HTTP_204_NO_CONTENT)
def ban_provider_customer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: ProviderBanCreate,
) -> None:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    customer_governance_service.ban_customer(
        session,
        provider_id=provider_id,
        user_id=body.user_id,
        blocked_by_user_id=current_user.id,
        reason=body.reason,
    )


@router.delete(
    "/{provider_id}/customers/{user_id}/ban",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unban_provider_customer(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    customer_governance_service.unban_customer(
        session, provider_id=provider_id, user_id=user_id
    )


@router.post("/{provider_id}/profile-image", response_model=ProviderPublic)
async def upload_provider_profile_image(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    file: UploadFile = File(...),
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    p = await provider_service.upload_provider_profile_image(
        session, provider_id=provider_id, upload=file
    )
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


@router.post("/{provider_id}/pause-queue", response_model=ProviderPublic)
def pause_provider_queue(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    """Pause **remote** queue joins for this business (walk-ins still allowed when open)."""
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    p = provider_service.set_provider_queue_paused(
        session, provider_id, paused=True
    )
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@router.post("/{provider_id}/resume-queue", response_model=ProviderPublic)
def resume_provider_queue(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    """Resume **remote** queue joins after ``pause-queue``."""
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    p = provider_service.set_provider_queue_paused(
        session, provider_id, paused=False
    )
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


@router.get("/{provider_id}/members", response_model=list[ProviderMemberPublic])
def list_provider_members(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    rows = provider_service.list_provider_members(session, provider_id)
    return [{"membership": m, "user": u} for m, u in rows]


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


@router.get(
    "/{provider_id}/documents",
    response_model=list[ProviderDocumentPublic],
)
def list_provider_documents(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    if provider_service.get_provider(session, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not current_user.is_superuser:
        ensure_provider_staff(
            session=session,
            current_user=current_user,
            provider_id=provider_id,
        )
    rows = documents_service.list_documents(session, provider_id=provider_id)
    return [documents_service.document_public(r) for r in rows]


@router.get("/{provider_id}/documents/{doc_id}/file")
def download_provider_document(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    doc_id: uuid.UUID,
) -> Any:
    if provider_service.get_provider(session, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not current_user.is_superuser:
        ensure_provider_staff(
            session=session,
            current_user=current_user,
            provider_id=provider_id,
        )
    url = documents_service.get_delivery_url(
        session, provider_id=provider_id, doc_id=doc_id
    )
    return RedirectResponse(url=url, status_code=307)


me_router = APIRouter(prefix="/users/me/providers", tags=["providers"])


@me_router.get("/", response_model=MyProvidersPublic)
def list_my_providers(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    role: str | None = Query(
        default=None,
        description=(
            "Optional membership role filter. Use 'owner' to list only "
            "businesses the user owns; omit to list every provider where "
            "they have any membership."
        ),
    ),
) -> Any:
    """List every provider the logged-in user has a membership in.

    Returns the same fields as ``GET /providers/{id}`` plus
    ``membership_role`` (``owner`` / ``staff``) so the dashboard can
    badge the row without an extra round trip. Sorted by newest first.
    """
    rows = provider_service.list_providers_for_user(
        session, user_id=current_user.id, role=role
    )
    items = [
        MyProviderPublic.model_validate(
            p,
            update={
                **provider_public_view(p),
                "membership_role": member_role,
                "last_rejection_reason": p.last_rejection_reason,
            },
        )
        for p, member_role in rows
    ]
    return MyProvidersPublic(data=items, count=len(items))


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
    p = provider_service.admin_verify_provider(
        session, provider_id, actor=_admin
    )
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@admin_router.post("/{provider_id}/reject", response_model=ProviderPublic)
def admin_reject_provider(
    *,
    session: SessionDep,
    _admin: SuperUser,
    provider_id: uuid.UUID,
    body: ProviderRejectBody,
) -> Any:
    """Admin (UC-10) marks a provider as ``rejected`` — it stays out of
    public discovery and the owner sees the status on their dashboard."""
    p = provider_service.admin_reject_provider(
        session, provider_id, actor=_admin, reason=body.reason
    )
    return ProviderPublic.model_validate(p, update=provider_public_view(p))


@admin_router.post(
    "/{provider_id}/documents",
    response_model=ProviderDocumentPublic,
)
async def admin_upload_provider_document(
    *,
    session: SessionDep,
    _admin: SuperUser,
    provider_id: uuid.UUID,
    file: UploadFile = File(...),
) -> Any:
    if provider_service.get_provider(session, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    row = documents_service.store_provider_document(
        session,
        provider_id=provider_id,
        uploader=_admin,
        upload=file,
    )
    return documents_service.document_public(row)
