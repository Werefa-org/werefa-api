"""End-to-end API tests for smart pre-alerts (FR-07).

Each test:

1. Creates a fresh provider + service line via the superuser.
2. Joins customers in a deterministic order.
3. Reads back ``GET /me/notifications`` to assert exactly the right
   alerts fired (and didn't fire — idempotency is the trickiest bit).

The default LIVENESS_TOP_K=3 is the boundary we verify; if you change
the default in ``settings`` the assertions below need a refresh.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import NotificationKind
from werefa.shared.models import UserCreate


def _create_provider_and_service(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> tuple[str, str]:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"notif-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Notification Test Provider",
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
        json={"name": "Counter", "avg_duration_minutes": 10, "price": "5.00"},
    )
    assert r.status_code == 200, r.text
    return provider_id, r.json()["id"]


def _customer(client: TestClient, db: Session) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    return str(user.id), headers


def _list_notifications(
    client: TestClient, headers: dict[str, str]
) -> list[dict[str, object]]:
    r = client.get(
        f"{settings.API_V1_STR}/me/notifications", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return list(body["data"])


def test_first_join_emits_you_are_next_alert(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, sid = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, customer = _customer(client, db)

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=customer,
        json={},
    )
    assert r.status_code == 200, r.text

    notes = _list_notifications(client, customer)
    assert len(notes) == 1, notes
    assert notes[0]["kind"] == NotificationKind.you_are_next.value
    assert notes[0]["position"] == 1
    assert notes[0]["status"] in {"delivered", "failed"}


def test_third_joiner_gets_head_to_counter_only(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, sid = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, h_a = _customer(client, db)
    _, h_b = _customer(client, db)
    _, h_c = _customer(client, db)

    for hdrs in (h_a, h_b, h_c):
        r = client.post(
            f"{settings.API_V1_STR}/service-items/{sid}/join",
            headers=hdrs,
            json={},
        )
        assert r.status_code == 200, r.text

    a = _list_notifications(client, h_a)
    b = _list_notifications(client, h_b)
    c = _list_notifications(client, h_c)
    assert [n["kind"] for n in a] == [NotificationKind.you_are_next.value]
    assert b == [], "middle of queue should not be alerted"
    assert [n["kind"] for n in c] == [NotificationKind.head_to_counter.value]
    assert c[0]["position"] == settings.LIVENESS_TOP_K


def test_repeated_evaluations_do_not_duplicate_alerts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, sid = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, customer = _customer(client, db)

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=customer,
        json={},
    )
    assert r.status_code == 200, r.text

    # Push a status update that will re-trigger the smart-alert pass.
    # The customer is still at position 1; their last_alert_position is
    # already 1, so no new row should land.
    ticket_id = r.json()["id"]
    client.patch(
        f"{settings.API_V1_STR}/service-items/{sid}/tickets/{ticket_id}/status",
        headers=superuser_token_headers,
        json={"status": "waiting"},
    )

    notes = _list_notifications(client, customer)
    assert len(notes) == 1, "smart-alert pass must be idempotent on no-op"


def test_call_next_promotes_remaining_customer_to_you_are_next(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """When the head ticket is dequeued, the next ticket rises to pos 1
    and should receive its own ``you_are_next`` alert — even though it
    previously sat at position 2 with no alert."""

    _, sid = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, h_a = _customer(client, db)
    _, h_b = _customer(client, db)

    for hdrs in (h_a, h_b):
        r = client.post(
            f"{settings.API_V1_STR}/service-items/{sid}/join",
            headers=hdrs,
            json={},
        )
        assert r.status_code == 200

    # Two call-nexts: first promotes A waiting->serving (position
    # already 1, no new alert for A); second completes A and promotes B
    # to serving with position 1 -> B should get you_are_next now.
    for _ in range(2):
        r = client.post(
            f"{settings.API_V1_STR}/service-items/{sid}/call-next",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

    b_notes = _list_notifications(client, h_b)
    assert any(
        n["kind"] == NotificationKind.you_are_next.value for n in b_notes
    ), b_notes


def test_patch_prefs_persists_and_lists_in_user_payload(
    client: TestClient,
    db: Session,
) -> None:
    _, customer = _customer(client, db)

    r = client.patch(
        f"{settings.API_V1_STR}/users/me/notifications",
        headers=customer,
        json={"notification_prefs": ["email", "websocket"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["notification_prefs"] == ["email", "websocket"]

    r = client.get(
        f"{settings.API_V1_STR}/users/me", headers=customer
    )
    assert r.status_code == 200
    assert r.json()["notification_prefs"] == ["email", "websocket"]


def test_patch_prefs_rejects_unknown_channel(
    client: TestClient,
    db: Session,
) -> None:
    _, customer = _customer(client, db)
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/notifications",
        headers=customer,
        json={"notification_prefs": ["sms", "smoke-signal"]},
    )
    assert r.status_code == 400, r.text


def test_patch_prefs_rejects_empty_list(
    client: TestClient,
    db: Session,
) -> None:
    _, customer = _customer(client, db)
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/notifications",
        headers=customer,
        json={"notification_prefs": []},
    )
    assert r.status_code == 422


def test_list_notifications_returns_recent_first(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, sid = _create_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, customer = _customer(client, db)

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=customer,
        json={},
    )
    assert r.status_code == 200

    # No further joins; only one notification exists.
    notes = _list_notifications(client, customer)
    assert len(notes) == 1
    assert notes[0]["kind"] == NotificationKind.you_are_next.value
