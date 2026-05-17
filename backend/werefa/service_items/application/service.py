import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from werefa.queue.application import join_documents_service
from werefa.queue.domain import ticket_rules
from werefa.service_items.infrastructure import repo as service_item_repo
from werefa.shared.models import (
    JoinDocumentRequirement,
    Provider,
    QueueEntry,
    ServiceItem,
    ServiceItemCreate,
    ServiceItemUpdate,
)


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
    return service_item_repo.create_service_item(
        session=session, provider_id=provider_id, body=body
    )


def update_service_item(
    session: Session,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID,
    body: ServiceItemUpdate,
) -> ServiceItem:
    row = session.get(ServiceItem, service_item_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Service not found")
    data = body.model_dump(exclude_unset=True)
    raw_reqs = data.pop("join_document_requirements", None)
    requires_docs = data.pop("requires_join_documents", None)
    if raw_reqs is not None or requires_docs is not None:
        parsed: list[JoinDocumentRequirement] | None = None
        if raw_reqs is not None:
            parsed = join_documents_service.parse_requirements(raw_reqs)
        flag, payload = join_documents_service.validate_requirements_for_service(
            row,
            requires=requires_docs,
            requirements=parsed,
        )
        data["requires_join_documents"] = flag
        data["join_document_requirements"] = payload
    row.sqlmodel_update(data)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_service_item(
    session: Session, provider_id: uuid.UUID, service_item_id: uuid.UUID
) -> None:
    """Hard-delete a service line when no tickets are ``waiting`` or ``serving``.

    Historical tickets in terminal states are removed via FK cascade when the
    service row is deleted (FR-10 guard: block only active queue members).
    """
    row = session.get(ServiceItem, service_item_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Service not found")

    active_count_raw = session.exec(
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(col(QueueEntry.status).in_(ticket_rules.active_status_values()))
    ).one()
    if isinstance(active_count_raw, tuple):
        active_count_raw = active_count_raw[0]
    active_count = int(active_count_raw or 0)
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete this service while tickets are waiting or being "
                "served. Complete, cancel, or no-show them first."
            ),
        )

    session.delete(row)
    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete this service: dependent records exist.",
        ) from err
