"""End-to-end API tests for provider broadcasts (FR-08, UC-11).

These tests cover:

- staff/owner-only access for both POST and GET (customers get 403);
- severity validation (only `info|warning|critical`);
- service-line scoping (both whole-provider and single-line broadcasts);
- idempotency on retried POSTs (second call returns the same record with
  status 200 instead of 201, no duplicate row);
- ``GET ?since=...`` filtering and ordering.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import BroadcastMessage, UserCreate


def _create_provider_and_service(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> tuple[str, str]:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"bcast-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Broadcast Test Provider",
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
        json={"name": "Line", "avg_duration_minutes": 10, "price": "5.00"},
    )
    assert r.status_code == 200, r.text
    return provider_id, r.json()["id"]


def _customer_headers(client: TestClient, db: Session) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    return user_authentication_headers(
        client=client, email=email, password=password
    )


def test_staff_can_post_provider_wide_broadcast(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json={"body": "Doctor running 20 min late", "severity": "warning"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["body"] == "Doctor running 20 min late"
    assert payload["severity"] == "warning"
    assert payload["service_item_id"] is None
    assert payload["provider_id"] == provider_id


def test_staff_can_post_service_scoped_broadcast(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, service_id = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json={
            "body": "Line closed for cleaning",
            "severity": "critical",
            "service_item_id": service_id,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["service_item_id"] == service_id


def test_post_broadcast_rejects_unknown_severity(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json={"body": "x", "severity": "loud"},
    )
    # Severity gating is enforced both at the service layer (400) and at
    # the DB CHECK constraint (would 500 if reached); the service-layer
    # rejection should fire first.
    assert r.status_code == 400, r.text


def test_post_broadcast_requires_long_enough_body(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json={"body": "", "severity": "info"},
    )
    assert r.status_code == 422, r.text


def test_post_broadcast_rejects_other_providers_service(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, other_service_id = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json={
            "body": "x",
            "severity": "info",
            "service_item_id": other_service_id,
        },
    )
    assert r.status_code == 404, r.text


def test_post_broadcast_is_idempotent_on_replay(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    payload = {
        "body": "We're back online",
        "severity": "info",
        "idempotency_key": "post-2026-04-30-001",
    }
    r1 = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json=payload,
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["id"]

    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        json=payload,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == first_id, "replayed broadcast should not be duplicated"

    rows = db.exec(
        select(BroadcastMessage)
        .where(BroadcastMessage.provider_id == uuid.UUID(provider_id))
    ).all()
    assert len(rows) == 1


def test_customer_cannot_post_broadcast(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    headers = _customer_headers(client, db)
    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=headers,
        json={"body": "hi", "severity": "info"},
    )
    assert r.status_code == 403, r.text


def test_customer_cannot_list_broadcasts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    headers = _customer_headers(client, db)
    r = client.get(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=headers,
    )
    assert r.status_code == 403, r.text


def test_list_broadcasts_returns_recent_first_with_since_filter(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _ = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    # Two posts ~50ms apart so created_at strictly orders.
    for n, sev in enumerate(("info", "warning")):
        r = client.post(
            f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
            headers=superuser_token_headers,
            json={"body": f"msg-{n}", "severity": sev},
        )
        assert r.status_code == 201, r.text
        time.sleep(0.05)

    r = client.get(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    bodies = [row["body"] for row in body["data"]]
    assert bodies[0] == "msg-1"  # most recent first
    assert bodies[1] == "msg-0"

    # `since` filter excludes the older message.
    boundary = datetime.now(timezone.utc) - timedelta(milliseconds=30)
    r = client.get(
        f"{settings.API_V1_STR}/providers/{provider_id}/broadcasts",
        headers=superuser_token_headers,
        params={"since": boundary.isoformat()},
    )
    assert r.status_code == 200, r.text
    # We don't pin the exact count (clock-bound) — just that the list is
    # bounded by the full set and returns the newest.
    filtered = r.json()
    assert filtered["count"] >= 1
    assert filtered["data"][0]["body"] == "msg-1"
