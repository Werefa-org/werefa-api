"""FR-05 liveness: top-K awaiting / ping / flagged."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import LivenessState
from werefa.shared.models import UserCreate


def _owner_id(db: Session) -> str:
    u = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert u is not None
    return str(u.id)


def _line(client: TestClient, db: Session, headers: dict[str, str]) -> str:
    slug = f"live-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=headers,
        json={"slug": slug, "biz_name": "Liv", "owner_user_id": _owner_id(db)},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=headers,
        json={"name": "Desk", "avg_duration_minutes": 10, "price": "1.00"},
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["id"]


def test_liveness_awaiting_when_in_top_k(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 3600
    sid = _line(client, db, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(client=client, email=email, password=password)
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    assert j.status_code == 200, j.text
    tid = j.json()["id"]

    r = client.get(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/liveness",
        headers=cust,
    )
    assert r.status_code == 200, r.text
    assert r.json()["liveness_state"] == LivenessState.awaiting.value


def test_position_ping_sets_ok(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 3600
    sid = _line(client, db, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(client=client, email=email, password=password)
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    tid = j.json()["id"]

    p = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={"latitude": 9.0, "longitude": 38.7},
    )
    assert p.status_code == 200, p.text
    assert p.json()["liveness_state"] == LivenessState.ok.value

    g = client.get(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/liveness",
        headers=cust,
    )
    assert g.json()["last_latitude"] == 9.0


def test_liveness_flags_after_grace(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 2
    sid = _line(client, db, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(client=client, email=email, password=password)
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    tid = j.json()["id"]

    far = datetime.now(timezone.utc) + timedelta(seconds=30)
    with mock.patch(
        "werefa.queue.application.liveness_service.utcnow",
        return_value=far,
    ):
        r = client.get(
            f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/liveness",
            headers=cust,
        )
    assert r.status_code == 200, r.text
    assert r.json()["liveness_state"] == LivenessState.flagged.value


def test_staff_can_read_customer_liveness(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(client=client, email=email, password=password)
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    tid = j.json()["id"]

    r = client.get(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/liveness",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ticket_id"] == tid


def test_stranger_cannot_ping_ticket(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(client=client, email=email, password=password)
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    tid = j.json()["id"]

    email2 = random_email()
    password2 = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email2, password=password2)
    )
    other = user_authentication_headers(
        client=client, email=email2, password=password2
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/position",
        headers=other,
        json={"latitude": 1.0, "longitude": 2.0},
    )
    assert r.status_code == 403
