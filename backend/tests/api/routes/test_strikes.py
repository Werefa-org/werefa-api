"""End-to-end API tests for the no-show penalty (FR-12).

The fixture builds one provider + one service line per test. Strike accrual
goes through the real ``set_ticket_status`` flow, so these tests exercise the
full transactional path: status → strike row → counter check → block window.
"""

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import TicketStatus
from werefa.shared.models import QueueEntry, User, UserCreate, UserStrike


@pytest.fixture(autouse=True)
def _restore_strike_settings() -> Generator[None, None, None]:
    """Reset strike thresholds to defaults after each test so leakage from
    a tweak in one test doesn't poison the next."""
    original = (
        settings.STRIKE_LIMIT,
        settings.STRIKE_WINDOW_DAYS,
        settings.STRIKE_BLOCK_DAYS,
    )
    yield
    (
        settings.STRIKE_LIMIT,
        settings.STRIKE_WINDOW_DAYS,
        settings.STRIKE_BLOCK_DAYS,
    ) = original


def _make_provider_and_service(
    *, client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> tuple[str, str]:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"strike-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Strike Test Provider",
            "owner_user_id": str(su.id),
            "latitude": 9.0,
            "longitude": 38.74,
        },
    )
    assert r.status_code == 200, r.text
    provider_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/",
        headers=superuser_token_headers,
        json={"name": "Cut", "avg_duration_minutes": 15, "price": "10.00"},
    )
    assert r.status_code == 200, r.text
    return provider_id, r.json()["id"]


def _register_customer(
    *, client: TestClient, db: Session
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    return user, headers


def _join_then_no_show(
    *,
    client: TestClient,
    db: Session,
    service_id: str,
    headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> str:
    """Join the queue, call the customer to ``serving``, then ``no_show``.

    Returns the ticket id so the caller can assert on it.
    """
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    ticket_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == ticket_id
    assert r.json()["status"] == TicketStatus.serving.value

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{service_id}/tickets/{ticket_id}/status",
        headers=superuser_token_headers,
        json={"status": "no_show"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == TicketStatus.no_show.value
    return ticket_id


def test_no_show_records_strike_for_remote_join(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    user, headers = _register_customer(client=client, db=db)

    ticket_id = _join_then_no_show(
        client=client,
        db=db,
        service_id=service_id,
        headers=headers,
        superuser_token_headers=superuser_token_headers,
    )

    rows = db.exec(
        select(UserStrike).where(UserStrike.user_id == user.id)
    ).all()
    assert len(rows) == 1
    assert str(rows[0].ticket_id) == ticket_id
    assert rows[0].kind == "no_show"


def test_no_show_does_not_strike_walk_in(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Walker"},
    )
    assert r.status_code == 200, r.text
    ticket_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == ticket_id

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{service_id}/tickets/{ticket_id}/status",
        headers=superuser_token_headers,
        json={"status": "no_show"},
    )
    assert r.status_code == 200, r.text

    rows = db.exec(select(UserStrike)).all()
    assert rows == []


def test_remote_join_blocked_after_threshold(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings.STRIKE_LIMIT = 3
    settings.STRIKE_WINDOW_DAYS = 30
    settings.STRIKE_BLOCK_DAYS = 7

    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    user, headers = _register_customer(client=client, db=db)

    for _ in range(3):
        _join_then_no_show(
            client=client,
            db=db,
            service_id=service_id,
            headers=headers,
            superuser_token_headers=superuser_token_headers,
        )

    db.expire_all()
    refreshed = db.get(User, user.id)
    assert refreshed is not None
    assert refreshed.joins_blocked_until is not None
    assert refreshed.joins_blocked_until > datetime.now(timezone.utc)

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["reason"] in {"explicit_block", "strike_threshold_reached"}
    assert detail["limit"] == 3
    assert detail["window_days"] == 30
    assert detail["joins_blocked_until"] is not None


def test_walk_in_still_works_when_user_is_blocked(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings.STRIKE_LIMIT = 3
    settings.STRIKE_WINDOW_DAYS = 30
    settings.STRIKE_BLOCK_DAYS = 7

    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    user, headers = _register_customer(client=client, db=db)

    for _ in range(3):
        _join_then_no_show(
            client=client,
            db=db,
            service_id=service_id,
            headers=headers,
            superuser_token_headers=superuser_token_headers,
        )

    # The penalty is for *remote* joins. Staff can still register a walk-in
    # under the same physical person.
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Walks-In"},
    )
    assert r.status_code == 200, r.text


def test_old_strikes_outside_window_do_not_block(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings.STRIKE_LIMIT = 3
    settings.STRIKE_WINDOW_DAYS = 30

    provider_id, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    user, headers = _register_customer(client=client, db=db)

    # Create three walk-in tickets and tie three strikes to them with a
    # back-dated ``created_at`` so we don't have to wait real time. The
    # user remains unblocked because all strikes fall outside the
    # 30-day window.
    old = datetime.now(timezone.utc) - timedelta(days=40)
    for _ in range(3):
        r = client.post(
            f"{settings.API_V1_STR}/service-items/{service_id}/walk-in",
            headers=superuser_token_headers,
            json={"guest_name": "T"},
        )
        assert r.status_code == 200, r.text
        tid = uuid.UUID(r.json()["id"])
        db.add(
            UserStrike(
                user_id=user.id,
                ticket_id=tid,
                provider_id=uuid.UUID(provider_id),
                kind="no_show",
                created_at=old,
            )
        )
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text


def test_get_my_strikes_returns_window_stats(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings.STRIKE_LIMIT = 3
    settings.STRIKE_WINDOW_DAYS = 30

    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, headers = _register_customer(client=client, db=db)

    _join_then_no_show(
        client=client,
        db=db,
        service_id=service_id,
        headers=headers,
        superuser_token_headers=superuser_token_headers,
    )

    r = client.get(f"{settings.API_V1_STR}/me/strikes", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["limit"] == 3
    assert body["window_days"] == 30
    assert body["joins_blocked_until"] is None  # not yet at threshold
    assert body["data"][0]["kind"] == "no_show"


def test_admin_unblock_user_clears_block(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings.STRIKE_LIMIT = 3
    settings.STRIKE_WINDOW_DAYS = 30
    settings.STRIKE_BLOCK_DAYS = 7

    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    user, headers = _register_customer(client=client, db=db)

    for _ in range(3):
        _join_then_no_show(
            client=client,
            db=db,
            service_id=service_id,
            headers=headers,
            superuser_token_headers=superuser_token_headers,
        )

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 403, r.text

    r = client.post(
        f"{settings.API_V1_STR}/admin/users/{user.id}/unblock",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["joins_blocked_until"] is None

    db.expire_all()
    # The user can join again immediately after the override; one waiting
    # ticket is enough to confirm the block was lifted.
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    # Cleanup: complete the new ticket so the next test starts clean.
    new_ticket_id = r.json()["id"]
    ticket = db.get(QueueEntry, uuid.UUID(new_ticket_id))
    if ticket is not None:
        db.delete(ticket)
        db.commit()


def test_admin_unblock_requires_superuser(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    user, headers = _register_customer(client=client, db=db)
    r = client.post(
        f"{settings.API_V1_STR}/admin/users/{user.id}/unblock",
        headers=headers,
    )
    assert r.status_code == 403, r.text
