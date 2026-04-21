import uuid

from sqlmodel import Session, select

from werefa.shared.enums import MembershipRole
from werefa.shared.models import Provider, ProviderCreate, ProviderMembership


def create_provider(*, session: Session, body: ProviderCreate) -> Provider:
    owner_id = body.owner_user_id
    data = body.model_dump(exclude={"owner_user_id"})
    p = Provider.model_validate(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    if owner_id is not None:
        m = ProviderMembership(
            provider_id=p.id, user_id=owner_id, role=MembershipRole.owner.value
        )
        session.add(m)
        session.commit()
    return p


def get_provider_by_slug(*, session: Session, slug: str) -> Provider | None:
    statement = select(Provider).where(Provider.slug == slug)
    return session.exec(statement).first()


def get_membership(
    *, session: Session, provider_id: uuid.UUID, user_id: uuid.UUID
) -> ProviderMembership | None:
    statement = select(ProviderMembership).where(
        ProviderMembership.provider_id == provider_id,
        ProviderMembership.user_id == user_id,
    )
    return session.exec(statement).first()
