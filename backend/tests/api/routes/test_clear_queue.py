"""End-of-day clear / reopen (UC-13).

Both halves are exercised through the real HTTP routes, because the bug these
tests pin down only shows up in the interaction between three of them: a line
with ``requires_join_approval`` produces ``pending_approval`` tickets, the
clear has to close them like every other active ticket, and the next morning's
reopen has to leave the customer able to join again.
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.queue.application.clear_queue_service import CLOSE_REASON_QUEUE_CLEARED
from werefa.shared.enums import LivenessState, NotificationKind, TicketStatus
from werefa.shared.models import Notification, QueueEntry, User, UserCreate


def _make_provider_and_service(
    *,
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    requires_join_approval: bool = False,
) -> tuple[str, str]:
    su = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert su is not None
    slug = f"clear-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=superuser_token_headers,
        json={
            "slug": slug,
            "biz_name": "Clear Test Provider",
            "owner_user_id": str(su.id),
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
            "price": "10.00",
            "requires_join_approval": requires_join_approval,
        },
    )
    assert r.status_code == 200, r.text
    return provider_id, r.json()["id"]


def _register_customer(
    *, client: TestClient, db: Session
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    headers = user_authentication_headers(
        client=client, email=email, password=password
    )
    return user, headers


def _join(
    *, client: TestClient, service_id: str, headers: dict[str, str]
) -> dict[str, str]:
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _clear(
    *, client: TestClient, service_id: str, headers: dict[str, str]
) -> dict[str, object]:
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/clear-queue",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _reopen(
    *, client: TestClient, service_id: str, headers: dict[str, str]
) -> dict[str, object]:
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/reopen-queue",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- clear: pending_approval is an active ticket like any other -------------


def test_clear_queue_closes_pending_approval_tickets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """A join awaiting review is active, so the clear must close it too."""
    _, service_id = _make_provider_and_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        requires_join_approval=True,
    )
    _, pending_headers = _register_customer(client=client, db=db)
    _, approved_headers = _register_customer(client=client, db=db)

    pending = _join(client=client, service_id=service_id, headers=pending_headers)
    assert pending["status"] == TicketStatus.pending_approval.value

    approved = _join(client=client, service_id=service_id, headers=approved_headers)
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}"
        f"/tickets/{approved['id']}/approve",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == TicketStatus.waiting.value

    body = _clear(
        client=client, service_id=service_id, headers=superuser_token_headers
    )
    # Both tickets counted, not just the waiting one.
    assert body["cleared_count"] == 2
    assert body["is_paused"] is True

    db.expire_all()
    for ticket_id in (pending["id"], approved["id"]):
        row = db.get(QueueEntry, uuid.UUID(ticket_id))
        assert row is not None
        assert row.status == TicketStatus.cancelled.value
        assert row.close_reason == CLOSE_REASON_QUEUE_CLEARED
        assert row.completed_at is not None


def test_clear_queue_leaves_no_approval_tickets_for_staff(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """No ticket is left awaiting a decision after a clear.

    The staff list deliberately keeps history, so this asserts on the *active*
    subset — which is what the approvals panel acts on.
    """
    _, service_id = _make_provider_and_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        requires_join_approval=True,
    )
    _, headers = _register_customer(client=client, db=db)
    _join(client=client, service_id=service_id, headers=headers)

    def _still_active() -> list[dict[str, str]]:
        r = client.get(
            f"{settings.API_V1_STR}/service-items/{service_id}/tickets",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200, r.text
        return [
            t
            for t in r.json()["data"]
            if t["status"]
            in (
                TicketStatus.waiting.value,
                TicketStatus.serving.value,
                TicketStatus.pending_approval.value,
            )
        ]

    assert len(_still_active()) == 1

    _clear(client=client, service_id=service_id, headers=superuser_token_headers)

    assert _still_active() == []

    # And the customer's own view agrees: nothing is still open for them.
    r = client.get(f"{settings.API_V1_STR}/service-items/me/tickets", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0


def test_clear_queue_notifies_the_pending_customer_about_the_request(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """A never-reviewed request is not "you lost your place in line"."""
    _, service_id = _make_provider_and_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        requires_join_approval=True,
    )
    user, headers = _register_customer(client=client, db=db)
    _join(client=client, service_id=service_id, headers=headers)

    body = _clear(
        client=client, service_id=service_id, headers=superuser_token_headers
    )
    assert body["notified_count"] == 1

    db.expire_all()
    rows = db.exec(
        select(Notification).where(Notification.user_id == user.id)
    ).all()
    cleared = [r for r in rows if r.kind == NotificationKind.queue_cleared.value]
    assert len(cleared) == 1
    assert "join request" in cleared[0].body
    assert "no longer in line" not in cleared[0].body


def test_clear_queue_clears_a_live_hold_on_the_closed_ticket(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """A closed ticket cannot still be parked (FR-05 hold)."""
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, headers = _register_customer(client=client, db=db)
    ticket = _join(client=client, service_id=service_id, headers=headers)

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}"
        f"/tickets/{ticket['id']}/liveness/hold",
        headers=superuser_token_headers,
        json={"hold_seconds": 300},
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    row = db.get(QueueEntry, uuid.UUID(ticket["id"]))
    assert row is not None and row.liveness_hold_until is not None

    _clear(client=client, service_id=service_id, headers=superuser_token_headers)

    db.expire_all()
    row = db.get(QueueEntry, uuid.UUID(ticket["id"]))
    assert row is not None
    assert row.status == TicketStatus.cancelled.value
    assert row.liveness_hold_until is None
    assert row.liveness_deadline_at is None
    assert row.liveness_state == LivenessState.idle.value


# --- reopen: the line takes joins again ------------------------------------


def test_reopen_lifts_the_pause_the_clear_set(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, headers = _register_customer(client=client, db=db)
    _join(client=client, service_id=service_id, headers=headers)

    _clear(client=client, service_id=service_id, headers=superuser_token_headers)

    _, next_day_headers = _register_customer(client=client, db=db)
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=next_day_headers,
        json={},
    )
    assert r.status_code == 400, r.text

    body = _reopen(
        client=client, service_id=service_id, headers=superuser_token_headers
    )
    assert body["is_paused"] is False
    assert body["remote_joins_open"] is True

    _join(client=client, service_id=service_id, headers=next_day_headers)


def test_cleared_approval_ticket_does_not_block_the_next_days_join(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """The regression: a leftover ``pending_approval`` row held the customer's
    one-active-ticket slot, so their next remote join was refused with 409
    long after the line reopened."""
    _, service_id = _make_provider_and_service(
        client=client,
        db=db,
        superuser_token_headers=superuser_token_headers,
        requires_join_approval=True,
    )
    _, headers = _register_customer(client=client, db=db)
    first = _join(client=client, service_id=service_id, headers=headers)
    assert first["status"] == TicketStatus.pending_approval.value

    _clear(client=client, service_id=service_id, headers=superuser_token_headers)
    _reopen(client=client, service_id=service_id, headers=superuser_token_headers)

    second = _join(client=client, service_id=service_id, headers=headers)
    assert second["id"] != first["id"]
    assert second["status"] == TicketStatus.pending_approval.value


def test_reopen_reports_a_business_wide_pause_it_cannot_lift(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """Reopening one line does not decide the whole business is open — but the
    caller is told which pause is still holding the door shut."""
    provider_id, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _clear(client=client, service_id=service_id, headers=superuser_token_headers)

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/pause-queue",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text

    body = _reopen(
        client=client, service_id=service_id, headers=superuser_token_headers
    )
    assert body["is_paused"] is False
    assert body["provider_is_paused"] is True
    assert body["remote_joins_open"] is False

    _, headers = _register_customer(client=client, db=db)
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join",
        headers=headers,
        json={},
    )
    assert r.status_code == 400, r.text

    r = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/resume-queue",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    _join(client=client, service_id=service_id, headers=headers)


def test_reopen_does_not_revive_cleared_tickets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    _, headers = _register_customer(client=client, db=db)
    ticket = _join(client=client, service_id=service_id, headers=headers)

    _clear(client=client, service_id=service_id, headers=superuser_token_headers)
    _reopen(client=client, service_id=service_id, headers=superuser_token_headers)

    db.expire_all()
    row = db.get(QueueEntry, uuid.UUID(ticket["id"]))
    assert row is not None
    assert row.status == TicketStatus.cancelled.value

    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/call-next",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() is None


def test_reopen_requires_provider_staff(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    _, service_id = _make_provider_and_service(
        client=client, db=db, superuser_token_headers=superuser_token_headers
    )
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/reopen-queue",
        headers=normal_user_token_headers,
    )
    assert r.status_code in (401, 403), r.text
