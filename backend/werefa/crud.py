import uuid
from typing import Any

from sqlmodel import Session, select

from werefa.core.security import get_password_hash, verify_password
from werefa.enums import MembershipRole
from werefa.models import (
    Provider,
    ProviderCreate,
    ProviderMembership,
    ServiceItem,
    ServiceItemCreate,
    User,
    UserCreate,
    UserUpdate,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_provider(*, session: Session, body: ProviderCreate) -> Provider:
    owner_id = body.owner_user_id
    data = body.model_dump(exclude={"owner_user_id"})
    p = Provider.model_validate(data)
    session.add(p)
    session.commit()
    session.refresh(p)
    if owner_id is not None:
        m = ProviderMembership(
            provider_id=p.id,
            user_id=owner_id,
            role=MembershipRole.owner.value,
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


def create_service_item(
    *, session: Session, provider_id: uuid.UUID, body: ServiceItemCreate
) -> ServiceItem:
    row = ServiceItem.model_validate(body, update={"provider_id": provider_id})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
