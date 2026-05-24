"""Public DTO helpers for queue entries."""

import uuid

from sqlmodel import Session, select

from werefa.shared.models import (
    ProviderCustomerBlock,
    QueueEntry,
    QueueEntryPublic,
    ServiceItem,
    User,
)


def queue_entry_to_public(session: Session, entry: QueueEntry) -> QueueEntryPublic:
    """Build ``QueueEntryPublic`` with provider + customer contact fields."""
    provider_id: uuid.UUID | None = None
    svc = session.get(ServiceItem, entry.service_item_id)
    if svc is not None:
        provider_id = svc.provider_id

    user_full_name: str | None = None
    user_email: str | None = None
    user_phone: str | None = None
    is_banned = False
    if entry.user_id is not None:
        user = session.get(User, entry.user_id)
        if user is not None:
            user_full_name = user.full_name
            user_email = str(user.email)
            user_phone = user.phone_number
        if provider_id is not None:
            blocked = session.exec(
                select(ProviderCustomerBlock.id).where(
                    ProviderCustomerBlock.provider_id == provider_id,
                    ProviderCustomerBlock.user_id == entry.user_id,
                )
            ).first()
            is_banned = blocked is not None

    base = QueueEntryPublic.model_validate(entry)
    return base.model_copy(
        update={
            "provider_id": provider_id,
            "user_full_name": user_full_name,
            "user_email": user_email,
            "user_phone": user_phone,
            "is_banned": is_banned,
        }
    )
