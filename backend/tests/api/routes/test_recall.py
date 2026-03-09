"""POST /service-items/{id}/recall — FR-09."""

import uuid
from unittest import mock

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import UserCreate


def _provider_and_line(
    *, client: TestClient, db: Session, staff_headers: dict[str, str]
) -> tuple[str, str]:
    owner = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert owner is not None
    slug = f"recall-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=staff_headers,
        json={
            "slug": slug,
            "biz_name": "Recall Test",
            "owner_user_id": str(owner.id),
            "latitude": 9.0,
            "longitude": 38.74,
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=staff_headers,
        json={"name": "Desk", "avg_duration_minutes": 10, "price": "1.00"},
    )
    assert r2.status_code == 200, r2.text
    return pid, r2.json()["id"]


def test_recall_puts_last_completed_back_on_serving(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Pat"},
    )
    assert r.status_code == 200, r.text
    tid = r.json()["id"]

    cn = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert cn.status_code == 200, cn.text
    assert cn.json()["status"] == "serving"

    done = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )
    assert done.status_code == 200, done.text

    rec = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/recall",
        headers=superuser_token_headers,
    )
    assert rec.status_code == 200, rec.text
    body = rec.json()
    assert body["id"] == tid
    assert body["status"] == "serving"
    assert body["completed_at"] is None


def test_recall_404_when_nothing_completed(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/recall",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404


def test_recall_409_while_serving(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={},
    )
    client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/recall",
        headers=superuser_token_headers,
    )
    assert r.status_code == 409


def test_recall_400_after_recall_window(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={},
    )
    tid = r.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    done = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )
    assert done.status_code == 200, done.text
    completed_at = done.json()["completed_at"]

    from datetime import datetime, timedelta

    ct = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    way_later = ct + timedelta(seconds=settings.RECALL_COMPLETED_WINDOW_SECONDS + 5)

    with mock.patch(
        "werefa.queue.application.service.utcnow",
        return_value=way_later,
    ):
        rec = client.post(
            f"{settings.API_V1_STR}/service-items/{sid}/recall",
            headers=superuser_token_headers,
        )
    assert rec.status_code == 400
    assert "recall" in rec.json()["detail"].lower()


def test_recall_forbidden_for_customer(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/recall",
        headers=headers,
    )
    assert r.status_code == 403


def test_recall_409_when_customer_already_rejoined(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    _pid, sid = _provider_and_line(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    cust = user_authentication_headers(
        client=client, email=email, password=password
    )

    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    assert j.status_code == 200, j.text
    tid = j.json()["id"]
    client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )

    j2 = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=cust,
        json={},
    )
    assert j2.status_code == 200, j2.text

    rec = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/recall",
        headers=superuser_token_headers,
    )
    assert rec.status_code == 409
