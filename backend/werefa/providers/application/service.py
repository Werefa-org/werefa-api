import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from werefa.providers.domain import membership_rules
from werefa.providers.infrastructure import repo as provider_repo
from werefa.shared.enums import MembershipRole
from werefa.shared.models import (
    MembershipCreate,
    Provider,
    ProviderCreate,
    ProviderMembership,
    ProviderUpdate,
    User,
)


def create_provider(session: Session, body: ProviderCreate) -> Provider:
    return provider_repo.create_provider(session=session, body=body)


def get_provider_by_slug(session: Session, slug: str) -> Provider | None:
    return provider_repo.get_provider_by_slug(session=session, slug=slug)


def get_provider(session: Session, provider_id: uuid.UUID) -> Provider | None:
    return session.get(Provider, provider_id)


def update_provider(
    session: Session, provider_id: uuid.UUID, body: ProviderUpdate
) -> Provider:
    p = session.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    data = body.model_dump(exclude_unset=True)
    p.sqlmodel_update(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def add_provider_member(
    session: Session, provider_id: uuid.UUID, body: MembershipCreate
) -> ProviderMembership:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if session.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=body.user_id
    ):
        raise HTTPException(status_code=409, detail="User is already a member")
    row = ProviderMembership(
        provider_id=provider_id,
        user_id=body.user_id,
        role=body.role.value,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_provider_members(
    session: Session, provider_id: uuid.UUID
) -> list[ProviderMembership]:
    rows = session.exec(
        select(ProviderMembership)
        .where(ProviderMembership.provider_id == provider_id)
        .order_by(col(ProviderMembership.role), col(ProviderMembership.user_id))
    ).all()
    return list(rows)


def remove_provider_member(
    session: Session, provider_id: uuid.UUID, member_user_id: uuid.UUID
) -> ProviderMembership:
    row = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=member_user_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    owner_count = len(
        session.exec(
            select(ProviderMembership)
            .where(ProviderMembership.provider_id == provider_id)
            .where(ProviderMembership.role == MembershipRole.owner.value)
        ).all()
    )
    try:
        membership_rules.validate_remove_last_owner(
            member_role=row.role, owner_count=owner_count
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    session.delete(row)
    session.commit()
    return row
