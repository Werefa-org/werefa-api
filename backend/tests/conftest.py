import secrets
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers
from werefa.core.config import settings

# Promote the JWT secret to a 32+ byte value before any module that might
# import it captures the short ".env" default. This silences PyJWT's
# `InsecureKeyLengthWarning` and exercises a production-like signature size.
if len(settings.SECRET_KEY) < 32:
    settings.SECRET_KEY = secrets.token_urlsafe(32)

from werefa.core.db import engine, init_db  # noqa: E402
from werefa.core.security import get_password_hash  # noqa: E402
from werefa.main import app  # noqa: E402
from werefa.shared.enums import UserType  # noqa: E402
from werefa.shared.models import (  # noqa: E402
    BroadcastMessage,
    Notification,
    Provider,
    ProviderMembership,
    QueueEntry,
    Review,
    ServiceItem,
    User,
    UserStrike,
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
    user.user_type = UserType.admin.value
    session.add(user)
    session.commit()
    session.refresh(user)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        _sync_superuser_password_with_settings(session)
        yield session
        session.exec(delete(Notification))
        session.exec(delete(BroadcastMessage))
        session.exec(delete(Review))
        session.exec(delete(UserStrike))
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


@pytest.fixture(autouse=True)
def _clear_provider_and_queue_between_tests(db: Session) -> Generator[None, None, None]:
    """Each test starts and ends without leftover providers or queue rows.

    The double clear (before yield + after yield) protects against module-scoped
    fixtures that might create state inside one test module and leak into the
    next one's first test.
    """

    def _clear() -> None:
        db.exec(delete(Notification))
        db.exec(delete(BroadcastMessage))
        db.exec(delete(Review))
        db.exec(delete(UserStrike))
        db.exec(delete(QueueEntry))
        db.exec(delete(ServiceItem))
        db.exec(delete(ProviderMembership))
        db.exec(delete(Provider))
        # Reset any block windows + saved channel prefs that previous tests
        # may have set on the shared superuser / module-scoped users.
        # Without this, a strike test leaves the next test's join request
        # 403, and a prefs test could change channel resolution mid-suite.
        from sqlmodel import update  # local import keeps this fixture lean

        db.exec(
            update(User).values(
                joins_blocked_until=None,
                notification_prefs=None,
            )
        )
        db.commit()
        db.expire_all()

    _clear()
    yield
    _clear()


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
