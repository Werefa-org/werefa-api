import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo


def _create_provider(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    slug_prefix: str,
    latitude: float,
    longitude: float,
    is_private: bool = False,
    is_open: bool = True,
    is_paused: bool = False,
    biz_name: str = "Discovery Test Provider",
) -> str:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": f"{slug_prefix}-{uuid.uuid4().hex[:8]}",
            "biz_name": biz_name,
            "owner_user_id": str(su.id),
            "latitude": latitude,
            "longitude": longitude,
            "is_private": is_private,
            "is_open": is_open,
            "is_paused": is_paused,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_discover_providers_public_open_and_sorted(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    near_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="near",
        latitude=9.01,
        longitude=38.75,
    )
    far_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="far",
        latitude=9.2,
        longitude=38.95,
    )
    _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="private",
        latitude=9.015,
        longitude=38.755,
        is_private=True,
    )
    _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="paused",
        latitude=9.02,
        longitude=38.76,
        is_paused=True,
    )
    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [row["id"] for row in body["data"]]
    assert near_id in ids
    assert far_id in ids
    assert body["count"] == 2
    assert ids[0] == near_id
    assert body["data"][0]["distance_m"] <= body["data"][1]["distance_m"]


def test_discover_providers_can_include_private_paused_and_radius_filter(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    open_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="open",
        latitude=9.0005,
        longitude=38.7405,
    )
    private_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="private2",
        latitude=9.0007,
        longitude=38.7407,
        is_private=True,
    )
    paused_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="paused2",
        latitude=9.0009,
        longitude=38.7409,
        is_paused=True,
    )
    closed_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="closed2",
        latitude=9.0011,
        longitude=38.7411,
        is_open=False,
    )
    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={
            "latitude": 9.0,
            "longitude": 38.74,
            "include_private": True,
            "include_paused": True,
            "only_open": False,
            "radius_m": 300,
        },
    )
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()["data"]}
    assert open_id in ids
    assert private_id in ids
    assert paused_id in ids
    assert closed_id in ids


def test_discover_providers_query_filter_by_name(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    hit_id = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="hair",
        latitude=9.05,
        longitude=38.78,
        biz_name="Hair Studio",
    )
    _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="clinic",
        latitude=9.051,
        longitude=38.781,
        biz_name="Dental Clinic",
    )
    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74, "query": "hair"},
    )
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()["data"]]
    assert ids == [hit_id]


def test_discover_provider_returns_load_hints(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    pid = _create_provider(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        slug_prefix="load",
        latitude=9.06,
        longitude=38.79,
    )
    s = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=superuser_token_headers,
        json={"name": "Haircut", "avg_duration_minutes": 30, "price": "20.00"},
    )
    assert s.status_code == 200, s.text
    sid = s.json()["id"]
    w1 = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "A"},
    )
    assert w1.status_code == 200, w1.text
    w2 = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "B"},
    )
    assert w2.status_code == 200, w2.text
    nxt = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert nxt.status_code == 200, nxt.text
    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74, "query": "load"},
    )
    assert r.status_code == 200, r.text
    row = r.json()["data"][0]
    assert row["id"] == pid
    assert row["active_tickets"] == 2
    assert row["serving_tickets"] == 1
    assert row["estimated_wait_minutes"] == 30
    assert row["load_factor"] == "low"
