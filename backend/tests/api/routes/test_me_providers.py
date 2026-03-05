"""End-to-end tests for ``GET /users/me/providers``.

Confirms that:
  * a user who owns multiple businesses sees all of them in one call,
  * the ``membership_role`` field is populated and matches the row,
  * the ``role`` query filter is honoured,
  * an unrelated user gets an empty list (not a leak),
  * unauthenticated callers are rejected.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo


def _provider_create_json(*, owner_user_id: str, slug_prefix: str) -> dict:
    return {
        "slug": f"{slug_prefix}-{uuid.uuid4().hex[:10]}",
        "biz_name": f"{slug_prefix.title()} Biz",
        "owner_user_id": owner_user_id,
        "latitude": 9.0,
        "longitude": 38.74,
        "join_radius_m": 500,
    }


def _signup_provider_user(client: TestClient) -> tuple[str, dict[str, str]]:
    """Sign up a fresh provider-typed user and return (email, auth headers)."""
    email = f"prov-{uuid.uuid4().hex[:8]}@example.com"
    password = "longpassword1"
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "Multi Biz Owner",
            "user_type": "provider",
        },
    )
    assert r.status_code == 200, r.text
    token = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert token.status_code == 200, token.text
    return email, {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_me_providers_lists_every_owned_business(
    client: TestClient, db: Session
) -> None:
    email, headers = _signup_provider_user(client)
    owner = identity_repo.get_user_by_email(session=db, email=email)
    assert owner is not None

    coffee = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=headers,
        json=_provider_create_json(
            owner_user_id=str(owner.id), slug_prefix="coffee"
        ),
    )
    assert coffee.status_code == 200, coffee.text
    barber = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=headers,
        json=_provider_create_json(
            owner_user_id=str(owner.id), slug_prefix="barber"
        ),
    )
    assert barber.status_code == 200, barber.text

    r = client.get(
        f"{settings.API_V1_STR}/users/me/providers/", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    ids = {row["id"] for row in body["data"]}
    assert {coffee.json()["id"], barber.json()["id"]} == ids
    for row in body["data"]:
        assert row["membership_role"] == "owner"
        # CRIT-1 still holds: the public listing must not leak the
        # rotating access code.
        assert "access_code" not in row


def test_me_providers_role_filter(client: TestClient, db: Session) -> None:
    email, headers = _signup_provider_user(client)
    owner = identity_repo.get_user_by_email(session=db, email=email)
    assert owner is not None

    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=headers,
        json=_provider_create_json(
            owner_user_id=str(owner.id), slug_prefix="solo"
        ),
    )
    assert r.status_code == 200, r.text

    # owner filter returns the row.
    r = client.get(
        f"{settings.API_V1_STR}/users/me/providers/",
        headers=headers,
        params={"role": "owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1

    # staff filter excludes it (the user is owner, not staff).
    r = client.get(
        f"{settings.API_V1_STR}/users/me/providers/",
        headers=headers,
        params={"role": "staff"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0

    # bogus role rejected with 400.
    r = client.get(
        f"{settings.API_V1_STR}/users/me/providers/",
        headers=headers,
        params={"role": "boss"},
    )
    assert r.status_code == 400, r.text


def test_me_providers_does_not_leak_other_users_business(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json=_provider_create_json(
            owner_user_id=str(su.id), slug_prefix="admin"
        ),
    )
    assert r.status_code == 200, r.text

    # The default test user is a customer with no memberships — they
    # must see an empty list, not the admin's business.
    r = client.get(
        f"{settings.API_V1_STR}/users/me/providers/",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"data": [], "count": 0}


def test_me_providers_requires_auth(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me/providers/")
    assert r.status_code == 401, r.text
