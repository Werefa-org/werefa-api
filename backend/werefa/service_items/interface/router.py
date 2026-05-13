import uuid
from typing import Any

from fastapi import APIRouter, status

from werefa.api.deps import CurrentUser, SessionDep, ensure_provider_staff
from werefa.service_items.application import service as service_item_service
from werefa.shared.models import ServiceItemCreate, ServiceItemPublic, ServiceItemUpdate

router = APIRouter(prefix="/providers/{provider_id}/services", tags=["service-items"])


@router.get("/", response_model=list[ServiceItemPublic])
def list_service_items(
    *,
    session: SessionDep,
    provider_id: uuid.UUID,
) -> Any:
    return service_item_service.list_service_items(session, provider_id)


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
    return service_item_service.create_service_item(session, provider_id, body)


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
    return service_item_service.update_service_item(
        session, provider_id, service_item_id, body
    )


@router.delete(
    "/{service_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_service_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
) -> None:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    service_item_service.delete_service_item(
        session, provider_id, service_item_id
    )
