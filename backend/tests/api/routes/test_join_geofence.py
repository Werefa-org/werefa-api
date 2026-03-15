"""FR-04: remote join geofence vs ``Provider.join_radius_m``."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import UserCreate


def _staff_user_id(db: Session) -> str:
    u = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert u is not None
    return str(u.id)


def _geofenced_line(
    *,
    client: TestClient,
    db: Session,
    staff_headers: dict[str, str],
    join_radius_m: int,
) -> str:
    slug = f"geo-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=staff_headers,
        json={
            "slug": slug,
            "biz_name": "Geo Test",
            "owner_user_id": _staff_user_id(db),
            "latitude": 9.0,
            "longitude": 38.74,
            "join_radius_m": join_radius_m,
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=staff_headers,
        json={"name": "Line", "avg_duration_minutes": 10, "price": "1.00"},
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["id"]


def test_join_without_coords_ok_when_no_radius(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """``join_radius_m == null`` keeps legacy join bodies working."""
    slug = f"noradius-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "No radius",
            "owner_user_id": _staff_user_id(db),
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=superuser_token_headers,
        json={"name": "Line", "avg_duration_minutes": 10, "price": "1.00"},
    )
    sid = r2.json()["id"]

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


def test_join_requires_coords_when_radius_set(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _geofenced_line(
        client=client,
        db=db,
        staff_headers=superuser_token_headers,
        join_radius_m=500,
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
    assert j.status_code == 400
    assert "longitude" in j.json()["detail"].lower()


def test_join_rejects_outside_radius(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _geofenced_line(
        client=client,
        db=db,
        staff_headers=superuser_token_headers,
        join_radius_m=50,
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
        json={"latitude": 9.01, "longitude": 38.74},
    )
    assert j.status_code == 403
    assert "far" in j.json()["detail"].lower()


def test_join_accepts_inside_radius(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _geofenced_line(
        client=client,
        db=db,
        staff_headers=superuser_token_headers,
        join_radius_m=500,
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
        json={"latitude": 9.0, "longitude": 38.74},
    )
    assert j.status_code == 200, j.text
    assert j.json()["status"] == "waiting"


def test_join_rejects_unpaired_coordinate(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _geofenced_line(
        client=client,
        db=db,
        staff_headers=superuser_token_headers,
        join_radius_m=500,
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
        json={"latitude": 9.0},
    )
    assert j.status_code == 422
