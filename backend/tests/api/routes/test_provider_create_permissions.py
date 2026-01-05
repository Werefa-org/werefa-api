import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from werefa.core.config import settings


def _provider_create_json(*, owner_user_id: str) -> dict:
    return {
        "slug": f"biz-{uuid.uuid4().hex[:10]}",
        "biz_name": "Test Biz",
        "owner_user_id": owner_user_id,
        "latitude": 9.0,
        "longitude": 38.74,
        "join_radius_m": 500,
    }


def test_customer_token_cannot_create_provider(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    from werefa.identity.infrastructure import repo as identity_repo

    u = identity_repo.get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    assert u is not None
    assert u.user_type == "customer"

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=normal_user_token_headers,
        json=_provider_create_json(owner_user_id=str(u.id)),
    )
    assert r.status_code == 403
    assert "provider or administrator" in r.json()["detail"].lower()


def test_provider_account_can_create_own_business(
    client: TestClient, db: Session
) -> None:
    email = f"prov-{uuid.uuid4().hex[:8]}@example.com"
    password = "longpassword1"
    client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "Biz Owner",
            "user_type": "provider",
        },
    )
    token_r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert token_r.status_code == 200, token_r.text
    headers = {"Authorization": f"Bearer {token_r.json()['access_token']}"}

    from werefa.identity.infrastructure import repo as identity_repo

    u = identity_repo.get_user_by_email(session=db, email=email)
    assert u is not None
    assert u.user_type == "provider"

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=headers,
        json=_provider_create_json(owner_user_id=str(u.id)),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["slug"].startswith("biz-")


def test_superuser_can_create_provider_for_any_owner(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    from werefa.identity.infrastructure import repo as identity_repo

    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json=_provider_create_json(owner_user_id=str(su.id)),
    )
    assert r.status_code == 200, r.text
