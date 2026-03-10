"""DELETE /providers/{pid}/services/{sid} — FR-10 with active-ticket guard."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import ServiceItem, UserCreate


def _superuser_id(client: TestClient, super_headers: dict[str, str]) -> str:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=super_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _new_provider_with_service(
    *, client: TestClient, db: Session, super_headers: dict[str, str]
) -> tuple[str, str]:
    owner_id = _superuser_id(client, super_headers)
    slug = f"svc-del-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=super_headers,
        json={
            "slug": slug,
            "biz_name": "Delete Test",
            "owner_user_id": owner_id,
            "latitude": 9.0,
            "longitude": 38.74,
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=super_headers,
        json={"name": "Line A", "avg_duration_minutes": 10, "price": "9.99"},
    )
    assert r2.status_code == 200, r2.text
    return pid, r2.json()["id"]


def test_delete_service_succeeds_when_empty(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    r = client.delete(
        f"{settings.API_V1_STR}/providers/{pid}/services/{sid}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 204, r.text
    assert db.get(ServiceItem, uuid.UUID(sid)) is None


def test_delete_service_404_wrong_provider(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    other_pid = str(uuid.uuid4())
    r = client.delete(
        f"{settings.API_V1_STR}/providers/{other_pid}/services/{sid}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert db.get(ServiceItem, uuid.UUID(sid)) is not None


def test_delete_service_blocked_when_waiting_ticket(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=headers,
        json={},
    )
    assert j.status_code == 200, j.text

    r = client.delete(
        f"{settings.API_V1_STR}/providers/{pid}/services/{sid}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 409
    assert "waiting" in r.json()["detail"].lower() or "served" in r.json()[
        "detail"
    ].lower()


def test_delete_service_blocked_when_serving_ticket(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=headers,
        json={},
    )
    assert j.status_code == 200, j.text
    cn = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert cn.status_code == 200, cn.text
    assert cn.json()["status"] == "serving"

    r = client.delete(
        f"{settings.API_V1_STR}/providers/{pid}/services/{sid}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 409


def test_delete_service_succeeds_after_terminal_tickets_removed(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    j = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=headers,
        json={},
    )
    tid = j.json()["id"]
    cn = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert cn.status_code == 200, cn.text
    done = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )
    assert done.status_code == 200, done.text

    r = client.delete(
        f"{settings.API_V1_STR}/providers/{pid}/services/{sid}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 204, r.text
    db.expire_all()
    assert (
        db.exec(select(ServiceItem).where(ServiceItem.id == uuid.UUID(sid))).first()
        is None
    )


def test_delete_service_forbidden_for_non_staff(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    pid, sid = _new_provider_with_service(
        client=client, db=db, super_headers=superuser_token_headers
    )
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    r = client.delete(
        f"{settings.API_V1_STR}/providers/{pid}/services/{sid}",
        headers=headers,
    )
    assert r.status_code == 403
