"""End-to-end API tests for verified reviews (FR-11, UC-08)."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import UserCreate


def _provision_provider_with_service_and_completed_ticket(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> tuple[str, str, str, str, dict[str, str]]:
    """Create a provider + service, register a customer, run them through
    a full waiting → serving → completed cycle, and return everything
    the review tests need."""

    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None

    slug = f"reviews-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Review Test Provider",
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
        json={
            "name": "Consultation",
            "avg_duration_minutes": 15,
            "price": "20.00",
        },
    )
    assert r.status_code == 200, r.text
    service_id = r.json()["id"]

    email = random_email()
    password = random_lower_string()
    customer = identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    customer_headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=customer_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    ticket_id = r.json()["id"]

    # Drive the ticket through serving → completed via the staff "call-next"
    # transition, which mirrors what a real provider does.
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text  # picks the new ticket up to "serving"

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text  # marks the served ticket "completed"

    return provider_id, service_id, ticket_id, str(customer.id), customer_headers


def test_review_happy_path_updates_aggregates(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _, ticket_id, _, headers = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json={"rating": 5, "was_estimate_accurate": True, "comment": "great"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["rating"] == 5
    assert payload["was_estimate_accurate"] is True
    assert payload["ticket_id"] == ticket_id
    assert payload["provider_id"] == provider_id

    r = client.get(f"{settings.API_V1_STR}/providers/{provider_id}/rating")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["ratings_count"] == 1
    assert summary["rating_avg"] == 5.0
    assert summary["estimate_accuracy_rate"] == 1.0

    r = client.get(f"{settings.API_V1_STR}/providers/{provider_id}/reviews")
    assert r.status_code == 200, r.text
    listing = r.json()
    assert listing["count"] == 1
    assert listing["data"][0]["rating"] == 5


def test_review_requires_was_estimate_accurate(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, _, ticket_id, _, headers = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json={"rating": 4, "comment": "missing accuracy field"},
    )
    assert r.status_code == 422, r.text


def test_review_rating_bounds_are_enforced(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, _, ticket_id, _, headers = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    for bad in (0, 6, -1):
        r = client.post(
            f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
            headers=headers,
            json={"rating": bad, "was_estimate_accurate": True},
        )
        assert r.status_code == 422, (bad, r.text)


def test_review_only_owner_can_post(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, _, ticket_id, _, _ = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    other_email = random_email()
    other_password = random_lower_string()
    identity_repo.create_user(
        session=db,
        user_create=UserCreate(email=other_email, password=other_password),
    )
    other_headers = user_authentication_headers(
        client=client, email=other_email, password=other_password
    )

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=other_headers,
        json={"rating": 3, "was_estimate_accurate": False},
    )
    assert r.status_code == 400, r.text
    assert "your own tickets" in r.json()["detail"].lower()


def test_review_rejects_non_completed_ticket(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None

    slug = f"waiting-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Waiting Provider",
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
        json={"name": "Quick", "avg_duration_minutes": 10, "price": "5.00"},
    )
    assert r.status_code == 200, r.text
    service_id = r.json()["id"]

    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    ticket_id = r.json()["id"]

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json={"rating": 5, "was_estimate_accurate": True},
    )
    assert r.status_code == 400, r.text
    assert "completed" in r.json()["detail"].lower()


def test_review_duplicate_returns_409(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, _, ticket_id, _, headers = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    body = {"rating": 4, "was_estimate_accurate": True}
    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json=body,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json=body,
    )
    assert r.status_code == 409, r.text
    assert "already" in r.json()["detail"].lower()


def test_provider_discovery_exposes_rating_avg(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, _, ticket_id, _, headers = (
        _provision_provider_with_service_and_completed_ticket(
            client=client, db=db, superuser_token_headers=superuser_token_headers
        )
    )

    r = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/reviews",
        headers=headers,
        json={"rating": 4, "was_estimate_accurate": False},
    )
    assert r.status_code == 200, r.text

    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74},
    )
    assert r.status_code == 200, r.text
    matches = [p for p in r.json()["data"] if p["id"] == provider_id]
    assert matches, "provider should appear in discovery"
    assert matches[0]["ratings_count"] == 1
    assert matches[0]["rating_avg"] == 4.0
