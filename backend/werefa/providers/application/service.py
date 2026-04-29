import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.providers.domain import membership_rules
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application.ewt import (
    provider_ewt_minutes,
    round_minutes,
    service_line_ewt_minutes,
)
from werefa.shared.enums import MembershipRole
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


def create_provider(session: Session, body: ProviderCreate) -> Provider:
    return provider_repo.create_provider(session=session, body=body)


def get_provider_by_slug(session: Session, slug: str) -> Provider | None:
    return provider_repo.get_provider_by_slug(session=session, slug=slug)


def get_provider(session: Session, provider_id: uuid.UUID) -> Provider | None:
    return session.get(Provider, provider_id)


def provider_public_view(p: Provider) -> dict:
    """Derived fields shared by every provider read path.

    Routes use ``ProviderPublic.model_validate(p, update=provider_public_view(p))``
    to expose the rating aggregate without leaking ``ratings_sum`` directly.
    """
    count = p.ratings_count or 0
    rating_avg = round((p.ratings_sum or 0) / count, 2) if count > 0 else None
    return {"ratings_count": count, "rating_avg": rating_avg}


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
) -> list[ProviderMembership]:
    rows = session.exec(
        select(ProviderMembership)
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


def discover_providers(
    session: Session,
    *,
    latitude: float,
    longitude: float,
    radius_m: int | None,
    query: str | None,
    include_private: bool,
    only_open: bool,
    include_paused: bool,
    limit: int,
    offset: int,
) -> ProviderDiscoveriesPublic:
    pairs = provider_repo.list_discoverable_providers(
        session=session,
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
