import uuid
from math import asin, cos, radians, sin, sqrt

from sqlmodel import Session, col, select

from werefa.queue.application.ewt import CompletedSample
from werefa.shared.enums import MembershipRole, TicketStatus, VerificationStatus
from werefa.shared.models import (
    Provider,
    ProviderCreate,
    ProviderMembership,
    QueueEntry,
    ServiceItem,
)


def create_provider(
    *, session: Session, body: ProviderCreate, auto_verify: bool = False
) -> Provider:
    owner_id = body.owner_user_id
    data = body.model_dump(exclude={"owner_user_id"})
    if auto_verify:
        # Admin-initiated creates skip the manual KYC gate; the column
        # is set explicitly so the rest of the codebase doesn't need to
        # special-case "admin made this".
        data["verification_status"] = VerificationStatus.verified.value
    p = Provider.model_validate(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    if owner_id is not None:
        m = ProviderMembership(
            provider_id=p.id, user_id=owner_id, role=MembershipRole.owner.value
        )
        session.add(m)
        session.commit()
    return p


def get_provider_by_slug(*, session: Session, slug: str) -> Provider | None:
    statement = select(Provider).where(Provider.slug == slug)
    return session.exec(statement).first()


def get_membership(
    *, session: Session, provider_id: uuid.UUID, user_id: uuid.UUID
) -> ProviderMembership | None:
    statement = select(ProviderMembership).where(
        ProviderMembership.provider_id == provider_id,
        ProviderMembership.user_id == user_id,
    )
    return session.exec(statement).first()


def list_providers_for_user(
    *,
    session: Session,
    user_id: uuid.UUID,
    role: str | None = None,
) -> list[tuple[Provider, str]]:
    """Return every (provider, role) pair the user has a membership in.

    Used by ``GET /users/me/providers`` so a logged-in provider/staff
    can list their own businesses without remembering ids or slugs.
    The role is returned alongside the provider so the UI can badge
    "Owner" vs "Staff" rows.
    """
    statement = (
        select(Provider, ProviderMembership.role)
        .join(ProviderMembership, ProviderMembership.provider_id == Provider.id)  # type: ignore[arg-type]
        .where(ProviderMembership.user_id == user_id)
    )
    if role is not None:
        statement = statement.where(ProviderMembership.role == role)
    statement = statement.order_by(col(Provider.created_at).desc())
    rows = session.exec(statement).all()
    return [(p, r) for p, r in rows]


def distance_meters(
    *,
    base_lat: float,
    base_lon: float,
    target_lat: float,
    target_lon: float,
) -> int:
    """
    Great-circle distance (Haversine) in meters.
    """
    r = 6_371_000.0
    d_lat = radians(target_lat - base_lat)
    d_lon = radians(target_lon - base_lon)
    b_lat = radians(base_lat)
    t_lat = radians(target_lat)
    a = sin(d_lat / 2.0) ** 2 + cos(b_lat) * cos(t_lat) * sin(d_lon / 2.0) ** 2
    c = 2.0 * asin(sqrt(a))
    return int(round(r * c))


def list_discoverable_providers(
    *,
    session: Session,
    latitude: float,
    longitude: float,
    radius_m: int | None,
    query: str | None,
    region: str | None,
    city: str | None,
    include_private: bool,
    only_open: bool,
    include_paused: bool,
    include_unverified: bool,
    limit: int,
    offset: int,
) -> list[tuple[Provider, int]]:
    statement = (
        select(Provider)
        .where(col(Provider.latitude).is_not(None))
        .where(col(Provider.longitude).is_not(None))
    )
    if not include_private:
        statement = statement.where(col(Provider.is_private).is_(False))
    # UC-10: only verified providers are publicly discoverable. Admins
    # opt in to the rejected/pending pool via ``include_unverified``.
    if not include_unverified:
        statement = statement.where(
            col(Provider.verification_status) == VerificationStatus.verified.value
        )
    if region:
        r = region.strip()
        if r:
            statement = statement.where(col(Provider.region) == r)
    if city:
        c = city.strip()
        if c:
            statement = statement.where(col(Provider.city) == c)
    if query:
        q = f"%{query.lower()}%"
        statement = statement.where(
            col(Provider.biz_name).ilike(q)
            | col(Provider.slug).ilike(q)
            | col(Provider.category).ilike(q)
            | col(Provider.city).ilike(q)
            | col(Provider.region).ilike(q)
        )
    if only_open:
        statement = statement.where(col(Provider.is_open).is_(True))
    if not include_paused:
        statement = statement.where(col(Provider.is_paused).is_(False))
    rows = session.exec(statement).all()
    pairs: list[tuple[Provider, int]] = []
    for p in rows:
        if p.latitude is None or p.longitude is None:
            continue
        distance = distance_meters(
            base_lat=latitude,
            base_lon=longitude,
            target_lat=p.latitude,
            target_lon=p.longitude,
        )
        if radius_m is not None and distance > radius_m:
            continue
        pairs.append((p, distance))
    pairs.sort(key=lambda pair: pair[1])
    return pairs[offset : offset + limit]


def _discoverable_base_filters():
    return (
        col(Provider.latitude).is_not(None),
        col(Provider.longitude).is_not(None),
        col(Provider.is_private).is_(False),
        col(Provider.verification_status) == VerificationStatus.verified.value,
    )


def list_discovery_regions(*, session: Session) -> list[str]:
    statement = select(Provider.region).where(*_discoverable_base_filters())
    statement = statement.where(col(Provider.region).is_not(None)).where(
        col(Provider.region) != ""
    )
    statement = statement.distinct().order_by(col(Provider.region))
    rows = session.exec(statement).all()
    return sorted({str(r).strip() for r in rows if r})


def list_discovery_cities(*, session: Session, region: str | None = None) -> list[str]:
    """Distinct cities with at least one publicly discoverable provider."""
    statement = select(Provider.city).where(*_discoverable_base_filters())
    if region:
        r = region.strip()
        if r:
            statement = statement.where(col(Provider.region) == r)
    statement = statement.where(col(Provider.city).is_not(None)).where(
        col(Provider.city) != ""
    )
    statement = statement.distinct().order_by(col(Provider.city))
    rows = session.exec(statement).all()
    return sorted({str(r).strip() for r in rows if r})


def provider_active_ticket_counts(
    *, session: Session, provider_id: uuid.UUID
) -> tuple[int, int, list[ServiceItem], dict[uuid.UUID, int]]:
    """Return ``(active_total, serving_total, services, waiting_per_service)``.

    Used by both discovery (load factor) and EWT computation. Splitting
    counting from the EWT math keeps the latter pure.
    """
    services = session.exec(
        select(ServiceItem).where(ServiceItem.provider_id == provider_id)
    ).all()
    service_ids = [s.id for s in services]
    if not service_ids:
        return 0, 0, list(services), {}
    active_rows = session.exec(
        select(QueueEntry)
        .where(col(QueueEntry.service_item_id).in_(service_ids))
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
    ).all()
    waiting_per_service: dict[uuid.UUID, int] = {sid: 0 for sid in service_ids}
    serving = 0
    for row in active_rows:
        if row.status == TicketStatus.waiting.value:
            waiting_per_service[row.service_item_id] = (
                waiting_per_service.get(row.service_item_id, 0) + 1
            )
        elif row.status == TicketStatus.serving.value:
            serving += 1
    waiting_total = sum(waiting_per_service.values())
    return waiting_total + serving, serving, list(services), waiting_per_service


def list_completed_samples_for_service(
    *,
    session: Session,
    service_item_id: uuid.UUID,
    limit: int,
) -> list[CompletedSample]:
    """Most-recent completed serve durations for a service line.

    Tickets without a ``serving_started_at`` (e.g. completed before the
    Phase 8 migration ran) are skipped so the WMA only sees real samples.
    """
    statement = (
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(QueueEntry.status == TicketStatus.completed.value)
        .where(col(QueueEntry.serving_started_at).is_not(None))
        .where(col(QueueEntry.completed_at).is_not(None))
        .order_by(col(QueueEntry.completed_at).desc())
        .limit(limit)
    )
    rows = session.exec(statement).all()
    samples: list[CompletedSample] = []
    for r in rows:
        if r.serving_started_at is None or r.completed_at is None:
            continue  # belt-and-suspenders for type narrowing
        samples.append(
            CompletedSample(
                serving_started_at=r.serving_started_at,
                completed_at=r.completed_at,
            )
        )
    return samples
