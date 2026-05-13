import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import UserCreate


def test_provider_queue_flow(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"demo-{uuid.uuid4().hex[:8]}"

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Demo Salon",
            "owner_user_id": str(su.id),
        },
    )
    assert r.status_code == 200, r.text
    provider_id = r.json()["id"]

    r = client.get(f"{settings.API_V1_STR}/providers/by-slug/{slug}")
    assert r.status_code == 200
    assert r.json()["id"] == provider_id

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/",
        headers=superuser_token_headers,
        json={
            "name": "Haircut",
            "avg_duration_minutes": 30,
            "price": "25.00",
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert Decimal(r.json()["price"]) == Decimal("25.00")

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "waiting"
    tid = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert r.status_code == 409

    r = client.get(
        f"{settings.API_V1_STR}/service-items/me/tickets",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "no_show"},
    )
    assert r.status_code == 400
    assert "serving" in r.json()["detail"].lower()

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == tid
    assert r.json()["status"] == "serving"

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "no_show"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "no_show"

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert r.status_code == 200

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Walk"},
    )
    assert r.status_code == 200

    r = client.get(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json()["count"] >= 2

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["status"] == "serving"

    r = client.patch(
        f"{settings.API_V1_STR}/providers/{provider_id}",
        headers=superuser_token_headers,
        json={"is_paused": True},
    )
    assert r.status_code == 200
    assert r.json()["is_paused"] is True

    r = client.patch(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/{sid}",
        headers=superuser_token_headers,
        json={"name": "Haircut Plus"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Haircut Plus"


def test_private_queue_access_code(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"priv-{uuid.uuid4().hex[:8]}"

    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    fresh_headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Private",
            "is_private": True,
            "access_code": "abc123",
            "owner_user_id": str(su.id),
        },
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    r = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=superuser_token_headers,
        json={
            "name": "S",
            "avg_duration_minutes": 15,
            "price": "10.00",
        },
    )
    sid = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=fresh_headers,
        json={},
    )
    assert r.status_code == 403

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=fresh_headers,
        json={"access_code": "wrong"},
    )
    assert r.status_code == 403

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=fresh_headers,
        json={"access_code": "abc123"},
    )
    assert r.status_code == 200


def test_provider_forbidden_for_non_staff(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    r = client.patch(
        f"{settings.API_V1_STR}/providers/{uuid.uuid4()}/",
        headers=normal_user_token_headers,
        json={"is_paused": True},
    )
    assert r.status_code == 403


def test_pause_resume_queue_endpoints(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"pause-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={"slug": slug, "biz_name": "Pause Demo", "owner_user_id": str(su.id)},
    )
    assert r.status_code == 200, r.text
    provider_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/",
        headers=superuser_token_headers,
        json={
            "name": "Cut",
            "avg_duration_minutes": 20,
            "price": "15.00",
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/pause-queue",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/pause-queue",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is True

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert r.status_code == 400
    assert "not accepting" in r.json()["detail"].lower()

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Kiosk"},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/resume-queue",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_paused"] is False

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text


def test_ticket_status_transition_rules(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    fresh_headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None

    slug = f"trans-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={"slug": slug, "biz_name": "Transitions", "owner_user_id": str(su.id)},
    )
    provider_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/",
        headers=superuser_token_headers,
        json={"name": "Consult", "avg_duration_minutes": 20, "price": "30.00"},
    )
    sid = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=fresh_headers,
        json={},
    )
    tid = r.json()["id"]

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )
    assert r.status_code == 400

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "completed"},
    )
    assert r.status_code == 200

    r = client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{tid}/status",
        headers=superuser_token_headers,
        json={"status": "no_show"},
    )
    assert r.status_code == 400


def test_provider_membership_list_and_remove(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None

    email = random_email()
    password = random_lower_string()
    new_user = identity_repo.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )

    slug = f"member-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={"slug": slug, "biz_name": "Membership", "owner_user_id": str(su.id)},
    )
    provider_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/members",
        headers=superuser_token_headers,
        json={"user_id": str(new_user.id), "role": "staff"},
    )
    assert r.status_code == 200

    r = client.get(
        f"{settings.API_V1_STR}/providers/{provider_id}/members",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert len(r.json()) >= 2

    r = client.delete(
        f"{settings.API_V1_STR}/providers/{provider_id}/members/{new_user.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200

    r = client.delete(
        f"{settings.API_V1_STR}/providers/{provider_id}/members/{su.id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 400
