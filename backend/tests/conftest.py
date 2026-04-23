from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers
from werefa.core.config import settings
from werefa.core.db import engine, init_db
from werefa.core.security import get_password_hash
from werefa.main import app
from werefa.shared.models import (
    Provider,
    ProviderMembership,
    QueueEntry,
    ServiceItem,
    User,
)


def _sync_superuser_password_with_settings(session: Session) -> None:
    """
    Local/dev DBs often keep an old superuser row while .env has a new password.
    init_db only creates the user when missing, so align the hash for tests and dev.
    """
    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if user is None:
        return
    user.hashed_password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
    session.add(user)
    session.commit()
    session.refresh(user)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        _sync_superuser_password_with_settings(session)
        yield session
        session.exec(delete(QueueEntry))
        session.exec(delete(ServiceItem))
        session.exec(delete(ProviderMembership))
        session.exec(delete(Provider))
        session.exec(delete(User))
        session.commit()


@pytest.fixture(autouse=True)
def _expire_orm_caches_on_each_test(db: Session) -> Generator[None, None, None]:
    """Avoid stale identity-map reads when the app uses separate DB sessions per request."""
    db.expire_all()
    yield
    db.expire_all()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
