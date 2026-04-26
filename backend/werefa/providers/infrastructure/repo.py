import uuid
from math import asin, cos, radians, sin, sqrt

from sqlmodel import Session, col, select

from werefa.shared.enums import MembershipRole, TicketStatus
from werefa.shared.models import (
    Provider,
    ProviderCreate,
    ProviderMembership,
    QueueEntry,
    ServiceItem,
)


def create_provider(*, session: Session, body: ProviderCreate) -> Provider:
    owner_id = body.owner_user_id
    data = body.model_dump(exclude={"owner_user_id"})
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
    include_private: bool,
    only_open: bool,
    include_paused: bool,
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
    if query:
        q = f"%{query.lower()}%"
        statement = statement.where(
            col(Provider.biz_name).ilike(q) | col(Provider.slug).ilike(q)
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


def provider_queue_hints(
    *, session: Session, provider_id: uuid.UUID
) -> tuple[int, int, int | None]:
    services = session.exec(
        select(ServiceItem).where(ServiceItem.provider_id == provider_id)
    ).all()
    service_ids = [s.id for s in services]
    if not service_ids:
        return 0, 0, None
    active_rows = session.exec(
        select(QueueEntry)
        .where(col(QueueEntry.service_item_id).in_(service_ids))
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
    ).all()
    waiting = sum(1 for row in active_rows if row.status == TicketStatus.waiting.value)
    serving = sum(1 for row in active_rows if row.status == TicketStatus.serving.value)
    active_services = [s for s in services if s.is_active]
    if not active_services:
        return waiting + serving, serving, None
    avg_minutes = sum(s.avg_duration_minutes for s in active_services) / len(active_services)
    estimated_wait = int(round(waiting * avg_minutes))
    return waiting + serving, serving, estimated_wait
