import uuid

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, col, select

from werefa.core import cloudinary_storage
from werefa.core.config import settings
from werefa.core.image_upload import read_image_upload
from werefa.providers.domain import membership_rules
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application.ewt import (
    provider_ewt_minutes,
    round_minutes,
    service_line_ewt_minutes,
)
from werefa.shared.enums import MembershipRole, VerificationStatus
from werefa.shared.models import (
    MembershipCreate,
    Provider,
    ProviderCreate,
    ProviderDiscoveriesPublic,
    ProviderDiscoveryPublic,
    ProviderMembership,
    ProviderUpdate,
    ServiceItem,
    User,
    utcnow,
)


def create_provider(
    session: Session,
    body: ProviderCreate,
    *,
    auto_verify: bool = False,
) -> Provider:
    """Persist a provider with the supplied owner.

    ``auto_verify=True`` is set by the router when the caller is a
    superuser/admin; the resulting record skips the pending state. For
    self-signups (``user_type='provider'``) the column stays at
    ``pending`` until a separate admin verify call runs.
    """
    if body.owner_user_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "owner_user_id is required: every provider must have at "
                "least one owner so the business is manageable."
            ),
        )
    if session.get(User, body.owner_user_id) is None:
        raise HTTPException(
            status_code=400, detail="owner_user_id does not match any user"
        )
    return provider_repo.create_provider(
        session=session, body=body, auto_verify=auto_verify
    )


def admin_verify_provider(
    session: Session, provider_id: uuid.UUID, *, actor: User
) -> Provider:
    p = session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.verification_status = VerificationStatus.verified.value
    session.add(p)
    from werefa.admin.application import service as admin_service

    admin_service.log_admin_action(
        session,
        actor=actor,
        action="provider.verify",
        entity_type="provider",
        entity_id=provider_id,
        details=None,
    )
    session.commit()
    session.refresh(p)
    return p


def admin_reject_provider(
    session: Session, provider_id: uuid.UUID, *, actor: User, reason: str
) -> Provider:
    p = session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.verification_status = VerificationStatus.rejected.value
    p.last_rejection_reason = reason
    session.add(p)
    from werefa.admin.application import service as admin_service

    admin_service.log_admin_action(
        session,
        actor=actor,
        action="provider.reject",
        entity_type="provider",
        entity_id=provider_id,
        details={"reason": reason},
    )
    session.commit()
    session.refresh(p)
    return p


def get_provider_by_slug(session: Session, slug: str) -> Provider | None:
    return provider_repo.get_provider_by_slug(session=session, slug=slug)


def get_provider(session: Session, provider_id: uuid.UUID) -> Provider | None:
    return session.get(Provider, provider_id)


def profile_image_url_for_provider(p: Provider) -> str | None:
    if not p.profile_image_public_id:
        return None
    return cloudinary_storage.public_image_url(
        public_id=p.profile_image_public_id,
        resource_type=p.profile_image_resource_type or "image",
    )


def provider_public_view(p: Provider) -> dict:
    """Derived fields shared by every provider read path.

    Routes use ``ProviderPublic.model_validate(p, update=provider_public_view(p))``
    to expose the rating aggregate without leaking ``ratings_sum`` directly.
    """
    count = p.ratings_count or 0
    rating_avg = round((p.ratings_sum or 0) / count, 2) if count > 0 else None
    return {
        "ratings_count": count,
        "rating_avg": rating_avg,
        "profile_image_url": profile_image_url_for_provider(p),
    }


async def upload_provider_profile_image(
    session: Session,
    *,
    provider_id: uuid.UUID,
    upload: UploadFile,
) -> Provider:
    p = session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    data, ext = await read_image_upload(upload)
    stored = cloudinary_storage.upload_public_image(
        data=data,
        folder=f"{settings.CLOUDINARY_AVATARS_FOLDER}/providers/{provider_id}",
        asset_name=f"avatar.{ext}",
    )
    p.profile_image_public_id = stored.public_id
    p.profile_image_resource_type = stored.resource_type
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def list_providers_for_user(
    session: Session,
    *,
    user_id: uuid.UUID,
    role: str | None = None,
) -> list[tuple[Provider, str]]:
    """Service-layer wrapper for ``GET /users/me/providers``.

    Validates the optional role filter so the API rejects garbage role
    strings instead of silently returning an empty list.
    """
    if role is not None:
        valid = {r.value for r in MembershipRole}
        if role not in valid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown role '{role}'. Expected one of: "
                    f"{', '.join(sorted(valid))}."
                ),
            )
    return provider_repo.list_providers_for_user(
        session=session, user_id=user_id, role=role
    )


def update_provider(
    session: Session, provider_id: uuid.UUID, body: ProviderUpdate
) -> Provider:
    p = session.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    data = body.model_dump(exclude_unset=True)
    p.sqlmodel_update(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def set_provider_queue_paused(
    session: Session, provider_id: uuid.UUID, *, paused: bool
) -> Provider:
    """UC-13: toggle ``is_paused`` — halts **remote** joins; walk-ins unchanged."""
    p = session.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    p.is_paused = paused
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def add_provider_member(
    session: Session, provider_id: uuid.UUID, body: MembershipCreate
) -> ProviderMembership:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if session.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=body.user_id
    ):
        raise HTTPException(status_code=409, detail="User is already a member")
    row = ProviderMembership(
        provider_id=provider_id,
        user_id=body.user_id,
        role=body.role.value,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_provider_members(
    session: Session, provider_id: uuid.UUID
) -> list[tuple[ProviderMembership, User]]:
    rows = session.exec(
        select(ProviderMembership, User)
        .join(User, ProviderMembership.user_id == User.id)
        .where(ProviderMembership.provider_id == provider_id)
        .order_by(col(ProviderMembership.role), col(ProviderMembership.user_id))
    ).all()
    return list(rows)


def remove_provider_member(
    session: Session, provider_id: uuid.UUID, member_user_id: uuid.UUID
) -> ProviderMembership:
    row = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=member_user_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    owner_count = len(
        session.exec(
            select(ProviderMembership)
            .where(ProviderMembership.provider_id == provider_id)
            .where(ProviderMembership.role == MembershipRole.owner.value)
        ).all()
    )
    try:
        membership_rules.validate_remove_last_owner(
            member_role=row.role, owner_count=owner_count
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    session.delete(row)
    session.commit()
    return row


def list_discovery_cities(session: Session) -> list[str]:
    return provider_repo.list_discovery_cities(session=session)


def discover_providers(
    session: Session,
    *,
    latitude: float,
    longitude: float,
    radius_m: int | None,
    query: str | None,
    city: str | None,
    include_private: bool,
    only_open: bool,
    include_paused: bool,
    include_unverified: bool,
    limit: int,
    offset: int,
) -> ProviderDiscoveriesPublic:
    pairs = provider_repo.list_discoverable_providers(
        session=session,
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
    data: list[ProviderDiscoveryPublic] = []
    now = utcnow()
    for p, distance in pairs:
        active_tickets, serving_tickets, estimated_wait_minutes = (
            _compute_provider_load_and_ewt(session=session, provider=p, now=now)
        )
        if active_tickets <= 5:
            load_factor = "low"
        elif active_tickets <= 15:
            load_factor = "medium"
        else:
            load_factor = "high"
        rating_avg: float | None
        if (p.ratings_count or 0) > 0:
            rating_avg = round((p.ratings_sum or 0) / p.ratings_count, 2)
        else:
            rating_avg = None
        data.append(
            ProviderDiscoveryPublic.model_validate(
                p,
                update={
                    "distance_m": distance,
                    "active_tickets": active_tickets,
                    "serving_tickets": serving_tickets,
                    "estimated_wait_minutes": estimated_wait_minutes,
                    "load_factor": load_factor,
                    "ratings_count": p.ratings_count or 0,
                    "rating_avg": rating_avg,
                },
            )
        )
    return ProviderDiscoveriesPublic(data=data, count=len(data))


def _compute_provider_load_and_ewt(
    *,
    session: Session,
    provider: Provider,
    now,
) -> tuple[int, int, int | None]:
    """Compose the active-ticket counts with the EWT WMA per service line.

    Returns ``(active_total, serving_total, estimated_wait_minutes)`` so
    callers can stay shaped like the legacy ``provider_queue_hints``.
    """
    active_total, serving_total, services, waiting_per_service = (
        provider_repo.provider_active_ticket_counts(
            session=session, provider_id=provider.id
        )
    )
    if not services:
        return active_total, serving_total, None

    active_services: list[ServiceItem] = [s for s in services if s.is_active]
    if not active_services:
        return active_total, serving_total, None

    service_line_ewts: list[float | None] = []
    for svc in active_services:
        waiting_count = waiting_per_service.get(svc.id, 0)
        if waiting_count <= 0:
            continue
        samples = provider_repo.list_completed_samples_for_service(
            session=session,
            service_item_id=svc.id,
            limit=settings.EWT_HISTORY_LIMIT,
        )
        line_ewt = service_line_ewt_minutes(
            samples=samples,
            waiting_count=waiting_count,
            fallback_avg_min=svc.avg_duration_minutes,
            now=now,
            half_life_min=settings.EWT_HALF_LIFE_MIN,
            min_samples=settings.EWT_MIN_SAMPLES,
            history_limit=settings.EWT_HISTORY_LIMIT,
        )
        service_line_ewts.append(line_ewt)

    provider_ewt = provider_ewt_minutes(
        service_line_ewts=service_line_ewts,
        aggregation=settings.EWT_PROVIDER_AGGREGATION,
    )
    return active_total, serving_total, round_minutes(provider_ewt)
