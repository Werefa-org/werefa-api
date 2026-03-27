"""Demand funnel events and aggregates (UC-07)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from sqlmodel import Session, col, func, select

from werefa.shared.enums import DemandEventType
from werefa.shared.models import DemandEvent, utcnow


def record_demand_event(
    session: Session,
    *,
    event_type: DemandEventType | str,
    provider_id: uuid.UUID | None = None,
    service_item_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    client_ref: str | None = None,
    payload: dict | None = None,
    commit: bool = True,
) -> DemandEvent:
    kind = event_type.value if isinstance(event_type, DemandEventType) else event_type
    row = DemandEvent(
        event_type=kind,
        provider_id=provider_id,
        service_item_id=service_item_id,
        user_id=user_id,
        client_ref=client_ref,
        payload=payload,
    )
    session.add(row)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(row)
    return row


def demand_summary(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[tuple[str, int]]:
    """(event_type, count) pairs for admin dashboards."""
    now = utcnow()
    start = since or now.replace(year=now.year - 1)
    end = until or now
    statement = (
        select(DemandEvent.event_type, func.count())
        .where(col(DemandEvent.created_at) >= start)
        .where(col(DemandEvent.created_at) <= end)
        .group_by(DemandEvent.event_type)
        .order_by(DemandEvent.event_type)
    )
    return [(str(r[0]), int(r[1])) for r in session.exec(statement).all()]


def demand_events_csv(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50_000,
) -> str:
    now = utcnow()
    start = since or now.replace(year=now.year - 1)
    end = until or now
    rows = session.exec(
        select(DemandEvent)
        .where(col(DemandEvent.created_at) >= start)
        .where(col(DemandEvent.created_at) <= end)
        .order_by(col(DemandEvent.created_at))
        .limit(limit)
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "event_type",
            "provider_id",
            "service_item_id",
            "user_id",
            "client_ref",
            "created_at",
        ]
    )
    for r in rows:
        w.writerow(
            [
                str(r.id),
                r.event_type,
                str(r.provider_id) if r.provider_id else "",
                str(r.service_item_id) if r.service_item_id else "",
                str(r.user_id) if r.user_id else "",
                r.client_ref or "",
                r.created_at.isoformat() if r.created_at else "",
            ]
        )
    return buf.getvalue()
