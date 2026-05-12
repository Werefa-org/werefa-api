"""Queue snapshot for a ticket holder (seeker UX)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlmodel import Session

from werefa.core.config import settings
from werefa.providers.application.service import profile_image_url_for_provider
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application.ewt import service_line_ewt_minutes
from werefa.queue.application.service import list_queue_entries
from werefa.shared.enums import TicketStatus
from werefa.shared.models import (
    Provider,
    QueueAheadPreview,
    QueueEntry,
    ServiceItem,
    ServiceLinePreview,
    TicketQueueSnapshot,
    User,
    utcnow,
)


def build_ticket_queue_snapshot(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    ticket_id: uuid.UUID,
    user: User,
) -> TicketQueueSnapshot:
    svc = session.get(ServiceItem, service_item_id)
    if svc is None:
        raise HTTPException(status_code=404, detail="Service not found")
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None or ticket.service_item_id != service_item_id:
        raise HTTPException(status_code=404, detail="Ticket not found")

    staff = user.is_superuser or (
        provider_repo.get_membership(
            session=session, provider_id=svc.provider_id, user_id=user.id
        )
        is not None
    )
    if not staff and ticket.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your ticket")

    provider = session.get(Provider, svc.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    rows = list(list_queue_entries(session, service_item_id))
    waiting = [r for r in rows if r.status == TicketStatus.waiting.value]
    serving = [r for r in rows if r.status == TicketStatus.serving.value]
    vip_waiting = sum(1 for r in waiting if (r.priority or 0) > 0)

    your_position: int | None = None
    people_ahead = 0
    pace = "Updates when you are in line"
    estimated: int | None = None
    avg = svc.avg_duration_minutes

    if ticket.status == TicketStatus.pending_approval.value:
        pace = "Waiting for the business to approve your join request"
        wc = len(waiting)
        if wc > 0 or serving:
            samples = provider_repo.list_completed_samples_for_service(
                session=session,
                service_item_id=service_item_id,
                limit=settings.EWT_HISTORY_LIMIT,
            )
            line_ewt = service_line_ewt_minutes(
                samples=samples,
                waiting_count=wc + 1,
                fallback_avg_min=avg,
                now=utcnow(),
                half_life_min=settings.EWT_HALF_LIFE_MIN,
                min_samples=settings.EWT_MIN_SAMPLES,
                history_limit=settings.EWT_HISTORY_LIMIT,
            )
            if line_ewt is not None:
                estimated = max(0, int(round(line_ewt)))
    elif ticket.status == TicketStatus.waiting.value:
        ordered = sorted(
            waiting,
            key=lambda r: (-(r.priority or 0), r.ticket_number),
        )
        for idx, row in enumerate(ordered, start=1):
            if row.id == ticket.id:
                your_position = idx
                people_ahead = idx - 1
                break

    if ticket.status == TicketStatus.waiting.value:
        base = people_ahead * avg
        if serving:
            base += max(1, avg // 2)
        estimated = max(0, int(round(base))) if people_ahead > 0 or serving else 0
    elif ticket.status == TicketStatus.serving.value:
        estimated = 0

    if ticket.status == TicketStatus.pending_approval.value:
        pass
    elif estimated is None:
        pace = "Updates when you are in line"
    elif estimated <= 0:
        pace = "You are next or being served"
    else:
        low = max(1, int(estimated * 0.85))
        high = int(estimated * 1.15) + 1
        pace = f"About {low}–{high} min at current pace"

    ahead_preview: list[QueueAheadPreview] = []
    if ticket.status == TicketStatus.waiting.value:
        ordered = sorted(
            waiting,
            key=lambda r: (-(r.priority or 0), r.ticket_number),
        )
        for idx, row in enumerate(ordered[:3], start=1):
            ahead_preview.append(
                QueueAheadPreview(
                    ticket_number=row.ticket_number,
                    position=idx,
                    is_vip=(row.priority or 0) > 0,
                    is_you=row.id == ticket.id,
                )
            )

    return TicketQueueSnapshot(
        service_item_id=service_item_id,
        service_name=svc.name,
        provider_id=provider.id,
        biz_name=provider.biz_name,
        profile_image_url=profile_image_url_for_provider(provider),
        avg_duration_minutes=avg,
        waiting_count=len(waiting),
        serving_count=len(serving),
        vip_waiting_count=vip_waiting,
        your_ticket_id=ticket.id,
        your_ticket_number=ticket.ticket_number,
        your_position=your_position,
        people_ahead=people_ahead,
        estimated_wait_minutes=estimated,
        pace_note=pace,
        ahead_preview=ahead_preview,
    )


def build_service_line_preview(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> ServiceLinePreview:
    """Anonymous queue stats for seekers before they join."""
    svc = session.get(ServiceItem, service_item_id)
    if svc is None or not svc.is_active:
        raise HTTPException(status_code=404, detail="Service not found")
    provider = session.get(Provider, svc.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    rows = list(list_queue_entries(session, service_item_id))
    waiting = [r for r in rows if r.status == TicketStatus.waiting.value]
    serving = [r for r in rows if r.status == TicketStatus.serving.value]
    vip_waiting = sum(1 for r in waiting if (r.priority or 0) > 0)
    waiting_count = len(waiting)

    now = utcnow()
    samples = provider_repo.list_completed_samples_for_service(
        session=session,
        service_item_id=service_item_id,
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
    estimated: int | None = None
    if line_ewt is not None:
        estimated = max(0, int(round(line_ewt)))
        if serving and waiting_count > 0:
            estimated = max(
                estimated,
                int(round(svc.avg_duration_minutes * 0.5)),
            )
    elif waiting_count > 0:
        estimated = waiting_count * svc.avg_duration_minutes

    accepting = (
        provider.is_open
        and not provider.is_paused
        and not svc.is_paused
    )
    if not accepting:
        pace = "Remote joins are paused — check back soon"
    elif waiting_count == 0 and not serving:
        pace = "No one waiting — you may be seen right away"
    elif estimated is None or estimated <= 0:
        pace = "Short wait expected at current pace"
    else:
        low = max(1, int(estimated * 0.85))
        high = int(estimated * 1.15) + 1
        pace = f"About {low}–{high} min if you join now"

    return ServiceLinePreview(
        service_item_id=service_item_id,
        service_name=svc.name,
        provider_id=provider.id,
        biz_name=provider.biz_name,
        profile_image_url=profile_image_url_for_provider(provider),
        avg_duration_minutes=svc.avg_duration_minutes,
        waiting_count=waiting_count,
        serving_count=len(serving),
        vip_waiting_count=vip_waiting,
        estimated_wait_minutes=estimated,
        pace_note=pace,
        is_accepting_remote_joins=accepting,
    )
