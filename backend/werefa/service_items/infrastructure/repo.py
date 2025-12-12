import uuid

from sqlmodel import Session

from werefa.shared.models import ServiceItem, ServiceItemCreate


def create_service_item(
    *, session: Session, provider_id: uuid.UUID, body: ServiceItemCreate
) -> ServiceItem:
    row = ServiceItem.model_validate(body, update={"provider_id": provider_id})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
