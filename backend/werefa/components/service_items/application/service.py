import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from werefa import crud
from werefa.models import Provider, ServiceItem, ServiceItemCreate, ServiceItemUpdate


def list_service_items(session: Session, provider_id: uuid.UUID) -> list[ServiceItem]:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    rows = session.exec(
        select(ServiceItem)
        .where(ServiceItem.provider_id == provider_id)
        .where(ServiceItem.is_active == True)  # noqa: E712
        .order_by(col(ServiceItem.name))
    ).all()
    return list(rows)


def create_service_item(
    session: Session, provider_id: uuid.UUID, body: ServiceItemCreate
) -> ServiceItem:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return crud.create_service_item(session=session, provider_id=provider_id, body=body)


def update_service_item(
    session: Session,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
    body: ServiceItemUpdate,
) -> ServiceItem:
    row = session.get(ServiceItem, service_item_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Service not found")
    row.sqlmodel_update(body.model_dump(exclude_unset=True))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
