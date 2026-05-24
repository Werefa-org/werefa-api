"""NFR-02: offline kiosk batch ingest with idempotency."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlmodel import Session, select

from werefa.analytics.application.service import record_demand_event
from werefa.queue.application.service import get_service_for_update
from werefa.shared.enums import DemandEventType, TicketSource, TicketStatus
from werefa.shared.models import (
    KioskSyncBatch,
    KioskSyncBatchIn,
    KioskSyncBatchOut,
    Provider,
    QueueEntry,
    QueueEntryPublic,
)


def ingest_kiosk_walk_in_batch(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    body: KioskSyncBatchIn,
) -> KioskSyncBatchOut:
    existing = session.exec(
        select(KioskSyncBatch).where(
            KioskSyncBatch.service_item_id == service_item_id,
            KioskSyncBatch.idempotency_key == body.idempotency_key,
        )
    ).first()
    if existing is not None:
        raw = existing.result_json.get("tickets", [])
        tickets = [QueueEntryPublic.model_validate(d) for d in raw]
        return KioskSyncBatchOut(idempotent_replay=True, tickets=tickets)

    svc = get_service_for_update(session, service_item_id)
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is not active")

    provider = session.get(Provider, svc.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not provider.is_open:
        raise HTTPException(status_code=400, detail="Provider is closed")

    created: list[QueueEntry] = []
    for item in body.walk_ins:
        num = svc.next_ticket_number
        svc.next_ticket_number = num + 1
        ticket = QueueEntry(
            service_item_id=service_item_id,
            user_id=None,
            ticket_number=num,
            status=TicketStatus.waiting.value,
            source=TicketSource.kiosk_walk_in.value,
            guest_name=item.guest_name,
            guest_phone=item.guest_phone,
            guest_email=item.guest_email,
        )
        session.add(ticket)
        created.append(ticket)
    session.add(svc)
    session.flush()

    snapshots = [
        QueueEntryPublic.model_validate(t).model_dump(mode="json") for t in created
    ]
    batch = KioskSyncBatch(
        service_item_id=service_item_id,
        idempotency_key=body.idempotency_key,
        result_json={"tickets": snapshots},
    )
    session.add(batch)
    record_demand_event(
        session,
        event_type=DemandEventType.join_walk_in_batch,
        provider_id=provider.id,
        service_item_id=service_item_id,
        user_id=None,
        payload={
            "count": len(created),
            "idempotency_key": body.idempotency_key,
        },
        commit=False,
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    for t in created:
        session.refresh(t)
    return KioskSyncBatchOut(
        idempotent_replay=False,
        tickets=[QueueEntryPublic.model_validate(t) for t in created],
    )
