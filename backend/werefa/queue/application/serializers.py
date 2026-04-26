"""Public DTO helpers for queue entries."""

import uuid

from sqlmodel import Session

from werefa.shared.models import QueueEntry, QueueEntryPublic, ServiceItem


def queue_entry_to_public(session: Session, entry: QueueEntry) -> QueueEntryPublic:
    """Build ``QueueEntryPublic`` with ``provider_id`` resolved from the service line."""
    provider_id: uuid.UUID | None = None
    svc = session.get(ServiceItem, entry.service_item_id)
    if svc is not None:
        provider_id = svc.provider_id
    base = QueueEntryPublic.model_validate(entry)
    return base.model_copy(update={"provider_id": provider_id})
