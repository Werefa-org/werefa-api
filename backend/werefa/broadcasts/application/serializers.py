"""Public DTO helpers for provider broadcasts."""

import uuid

from sqlmodel import Session

from werefa.providers.infrastructure import repo as provider_repo
from werefa.shared.enums import MembershipRole
from werefa.shared.models import BroadcastMessage, BroadcastPublic, Provider


def _author_role_and_label(
    session: Session,
    *,
    provider_id: uuid.UUID,
    author_user_id: uuid.UUID,
) -> tuple[str, str]:
    provider = session.get(Provider, provider_id)
    biz = (provider.biz_name if provider else None) or "Business"
    membership = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=author_user_id
    )
    if membership is not None and membership.role == MembershipRole.owner.value:
        return MembershipRole.owner.value, biz
    return MembershipRole.staff.value, f"{biz} team"


def broadcast_to_public(session: Session, row: BroadcastMessage) -> BroadcastPublic:
    author_role, author_label = _author_role_and_label(
        session,
        provider_id=row.provider_id,
        author_user_id=row.author_user_id,
    )
    base = BroadcastPublic.model_validate(row)
    return base.model_copy(
        update={"author_role": author_role, "author_label": author_label}
    )


def broadcasts_to_public(
    session: Session, rows: list[BroadcastMessage]
) -> list[BroadcastPublic]:
    return [broadcast_to_public(session, r) for r in rows]
