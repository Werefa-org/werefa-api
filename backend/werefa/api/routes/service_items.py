import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from werefa import crud
from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.models import (
    Provider,
    ServiceItem,
    ServiceItemCreate,
    ServiceItemPublic,
    ServiceItemUpdate,
)

router = APIRouter(prefix="/providers/{provider_id}/services", tags=["service-items"])


@router.get("/", response_model=list[ServiceItemPublic])
def list_service_items(
    *,
    session: SessionDep,
    provider_id: uuid.UUID,
) -> Any:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    statement = (
        select(ServiceItem)
        .where(ServiceItem.provider_id == provider_id)
        .where(ServiceItem.is_active == True)  # noqa: E712
        .order_by(col(ServiceItem.name))
    )
    rows = session.exec(statement).all()
    return list(rows)


@router.post("/", response_model=ServiceItemPublic)
def create_service_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: ServiceItemCreate,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return crud.create_service_item(session=session, provider_id=provider_id, body=body)


@router.patch("/{service_item_id}", response_model=ServiceItemPublic)
def update_service_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
    body: ServiceItemUpdate,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    row = session.get(ServiceItem, service_item_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Service not found")
    data = body.model_dump(exclude_unset=True)
    row.sqlmodel_update(data)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
