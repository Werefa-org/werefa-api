import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from werefa import crud
from werefa.api.deps import (
    CurrentUser,
    SessionDep,
    SuperUser,
    ensure_provider_owner_or_super,
    ensure_provider_staff,
)
from werefa.models import (
    MembershipCreate,
    MembershipPublic,
    Provider,
    ProviderCreate,
    ProviderMembership,
    ProviderPublic,
    ProviderUpdate,
    User,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/", response_model=ProviderPublic)
def create_provider(
    *, session: SessionDep, _admin: SuperUser, body: ProviderCreate
) -> Any:
    return crud.create_provider(session=session, body=body)


@router.get("/by-slug/{slug}", response_model=ProviderPublic)
def read_provider_by_slug(*, session: SessionDep, slug: str) -> Any:
    p = crud.get_provider_by_slug(session=session, slug=slug)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p


@router.get("/{provider_id}", response_model=ProviderPublic)
def read_provider(*, session: SessionDep, provider_id: uuid.UUID) -> Any:
    p = session.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    return p


@router.patch("/{provider_id}", response_model=ProviderPublic)
def update_provider(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: ProviderUpdate,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    p = session.get(Provider, provider_id)
    if not p:
        raise HTTPException(status_code=404, detail="Provider not found")
    data = body.model_dump(exclude_unset=True)
    p.sqlmodel_update(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.post("/{provider_id}/members", response_model=MembershipPublic)
def add_provider_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    body: MembershipCreate,
) -> Any:
    ensure_provider_owner_or_super(
        session=session, current_user=current_user, provider_id=provider_id
    )
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if session.get(User, body.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if crud.get_membership(
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


@router.get("/{provider_id}/members", response_model=list[MembershipPublic])
def list_provider_members(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> Any:
    ensure_provider_staff(
        session=session, current_user=current_user, provider_id=provider_id
    )
    rows = session.exec(
        select(ProviderMembership)
        .where(ProviderMembership.provider_id == provider_id)
        .order_by(col(ProviderMembership.role), col(ProviderMembership.user_id))
    ).all()
    return list(rows)


@router.delete(
    "/{provider_id}/members/{member_user_id}", response_model=MembershipPublic
)
def remove_provider_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
    member_user_id: uuid.UUID,
) -> Any:
    ensure_provider_owner_or_super(
        session=session, current_user=current_user, provider_id=provider_id
    )
    row = crud.get_membership(
        session=session, provider_id=provider_id, user_id=member_user_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    if row.role == "owner":
        owner_count = session.exec(
            select(ProviderMembership)
            .where(ProviderMembership.provider_id == provider_id)
            .where(ProviderMembership.role == "owner")
        ).all()
        if len(owner_count) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Provider must keep at least one owner",
            )

    session.delete(row)
    session.commit()
    return row
