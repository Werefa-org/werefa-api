"""Discovery EWT integration tests (FR-06, FR-01).

Phase 8 replaced the legacy heuristic with a service-line WMA. These tests
verify the public ``estimated_wait_minutes`` field stays sensible on:

- cold start (no completed samples → fallback to ``avg_duration_minutes``);
- post-completion (real serve durations dominate the WMA);
- empty queues (zero waiting → zero EWT regardless of history).
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import TicketStatus
from werefa.shared.models import QueueEntry, UserCreate


def _make_provider_with_service(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    avg_duration_minutes: int = 20,
) -> tuple[str, str]:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"ewt-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "EWT Test Provider",
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
            "name": "Service",
            "avg_duration_minutes": avg_duration_minutes,
            "price": "10.00",
        },
    )
    assert r.status_code == 200, r.text
    return provider_id, r.json()["id"]


def _walk_in(
    *,
    client: TestClient,
    service_id: str,
    superuser_token_headers: dict[str, str],
    name: str = "X",
) -> str:
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_discovery_cold_start_uses_baseline(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, service_id = _make_provider_with_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        avg_duration_minutes=20,
    )

    # 3 walk-ins waiting, none completed yet → cold-start fallback applies.
    for n in ("A", "B", "C"):
        _walk_in(
            client=client,
            service_id=service_id,
            superuser_token_headers=superuser_token_headers,
            name=n,
        )

    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74},
    )
    assert r.status_code == 200, r.text
    rows = [p for p in r.json()["data"] if p["id"] == provider_id]
    assert rows, "provider should appear in discovery"
    # 3 waiting × 20 min baseline = 60 minutes (no samples yet).
    assert rows[0]["estimated_wait_minutes"] == 60


def test_discovery_uses_real_samples_after_completions(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    settings_override = (
        settings.EWT_MIN_SAMPLES,
        settings.EWT_HALF_LIFE_MIN,
    )
    settings.EWT_MIN_SAMPLES = 3
    settings.EWT_HALF_LIFE_MIN = 30.0
    try:
        provider_id, service_id = _make_provider_with_service(
            client=client,
            db=db,
            superuser_token_headers=superuser_token_headers,
            avg_duration_minutes=999,  # exaggerated baseline so we can prove
            # the WMA actually beats it.
        )

        # Three completed samples, each with a known 4-minute serve duration.
        # We back-date them so they look "fresh enough" to outweigh the
        # nonsense baseline. Direct DB write avoids racing real time.
        now = datetime.now(timezone.utc)
        sample_ticket_ids: list[uuid.UUID] = []
        for i in range(3):
            tid = _walk_in(
                client=client,
                service_id=service_id,
                superuser_token_headers=superuser_token_headers,
                name=f"H{i}",
            )
            sample_ticket_ids.append(uuid.UUID(tid))

        db.expire_all()
        for offset, tid in enumerate(sample_ticket_ids):
            row = db.get(QueueEntry, tid)
            assert row is not None
            row.status = TicketStatus.completed.value
            row.serving_started_at = now - timedelta(
                minutes=10 + offset * 5, seconds=0
            )
            row.completed_at = (
                now - timedelta(minutes=6 + offset * 5)
            )  # always a 4-minute serve
            db.add(row)
        db.commit()

        # Now create one waiting ticket and verify discovery surfaces a
        # ~4-minute EWT (driven by the WMA), not the 999-minute baseline.
        _walk_in(
            client=client,
            service_id=service_id,
            superuser_token_headers=superuser_token_headers,
            name="Wait",
        )

        r = client.get(
            f"{settings.API_V1_STR}/providers/discover",
            params={"latitude": 9.0, "longitude": 38.74},
        )
        assert r.status_code == 200, r.text
        rows = [p for p in r.json()["data"] if p["id"] == provider_id]
        assert rows
        ewt = rows[0]["estimated_wait_minutes"]
        assert ewt is not None
        # WMA over three 4-minute samples * 1 waiting ≈ 4. Allow ±1 for
        # rounding and the half-life weighting near the boundary.
        assert 3 <= ewt <= 5, ewt
    finally:
        settings.EWT_MIN_SAMPLES, settings.EWT_HALF_LIFE_MIN = settings_override


def test_discovery_zero_waiting_yields_zero_ewt(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    provider_id, service_id = _make_provider_with_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        avg_duration_minutes=15,
    )

    r = client.get(
        f"{settings.API_V1_STR}/providers/discover",
        params={"latitude": 9.0, "longitude": 38.74},
    )
    assert r.status_code == 200, r.text
    rows = [p for p in r.json()["data"] if p["id"] == provider_id]
    assert rows
    # No waiting tickets → EWT is zero, not None.
    assert rows[0]["estimated_wait_minutes"] == 0


def test_call_next_stamps_serving_started_at(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """Sanity check on the queue-side hook: a ticket that gets ``call-next``ed
    must have ``serving_started_at`` populated so the WMA can sample its
    duration after completion."""
    _, service_id = _make_provider_with_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        avg_duration_minutes=20,
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
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    ticket_id = uuid.UUID(r.json()["id"])

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    row = db.exec(
        select(QueueEntry).where(QueueEntry.id == ticket_id)
    ).first()
    assert row is not None
    assert row.status == TicketStatus.serving.value
    assert row.serving_started_at is not None
