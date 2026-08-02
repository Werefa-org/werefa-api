"""FR-05 liveness: top-K check-ins, two-stage flagging, and spot holds.

Three things are being defended here beyond the happy path:

* an honest customer with bad connectivity must never end up worse off
  than one who does nothing at all — a check-in with no location fix is
  worth exactly as much as one that carried coordinates;
* a customer who never confirms must still reach ``flagged``, however
  busy their app's background traffic looks; and
* a flag must lead somewhere — a held spot the line can move past —
  rather than quietly raising the odds of a no-show strike.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.queue.application import liveness_service
from werefa.shared.enums import (
    LivenessAction,
    LivenessState,
    NotificationChannel,
    NotificationKind,
    NotificationReach,
    NotificationStatus,
    TicketStatus,
)
from werefa.shared.models import (
    Notification,
    PositionPing,
    UserCreate,
    UserStrike,
)

API = settings.API_V1_STR

_LIVENESS_SETTINGS = (
    "LIVENESS_TOP_K",
    "LIVENESS_GRACE_SECONDS",
    "LIVENESS_MISSES_BEFORE_FLAG",
    "LIVENESS_ACTIVITY_GRACE_SECONDS",
    "LIVENESS_HOLD_SECONDS",
    "LIVENESS_MAX_HOLDS",
    "LIVENESS_ENABLED",
    "LIVENESS_AUTO_HOLD_UNREACHABLE",
    # Not a LIVENESS_* setting, but liveness reads it: it decides when an
    # unanswered delivery receipt stops being an open question.
    "NOTIFICATION_RECEIPT_GRACE_SECONDS",
)


@pytest.fixture(autouse=True)
def _restore_liveness_settings() -> Iterator[None]:
    """These tests tune global settings; put them back afterwards.

    Without this, a module that lowers ``LIVENESS_GRACE_SECONDS`` leaks
    into whatever runs next and produces failures nowhere near the cause.
    """
    saved = {name: getattr(settings, name) for name in _LIVENESS_SETTINGS}
    yield
    for name, value in saved.items():
        setattr(settings, name, value)


@pytest.fixture
def prompts_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as if every liveness prompt got through to the customer.

    Needed by every test about the *window state machine* — do consecutive
    silent windows warn, then flag? — because that machine only has
    something to decide once the customer was actually asked.

    In this environment nobody holds a websocket, SMTP is off and no SMS
    gateway is configured, so a prompt genuinely reaches nothing but the
    ``logger`` backstop. Liveness reads that (correctly) as "we never told
    them" and declines to flag, which would leave these tests asserting
    nothing. They used to pass because a websocket publish to zero
    subscribers reported itself delivered — the very falsehood this fixture
    now stands in for deliberately, in the open, rather than by accident.

    Tests about delivery itself must not use this. They build real ledger
    rows with :func:`_record_reach`.
    """
    _pin_prompt_reach(
        monkeypatch,
        NotificationReach.confirmed,
        channel=NotificationChannel.websocket,
        status=NotificationStatus.delivered,
    )


def _pin_prompt_reach(
    monkeypatch: pytest.MonkeyPatch,
    reach: NotificationReach,
    *,
    channel: NotificationChannel,
    status: NotificationStatus,
) -> None:
    from werefa.notifications.application.service import PromptDelivery

    entry = PromptDelivery(reach=reach, channel=channel, status=status)

    def _fake(
        session: Session, ticket_ids: list[uuid.UUID], *, now: datetime
    ) -> dict[uuid.UUID, object]:
        return dict.fromkeys(ticket_ids, entry)

    monkeypatch.setattr(liveness_service, "_reach_for", _fake)


@contextmanager
def _at(offset_seconds: float) -> Iterator[None]:
    """Run a block as if the clock had jumped forward.

    Every module that reads the wall clock for liveness decisions is
    patched: the liveness service (windows, holds), the queue service
    (whether a hold has expired at call time), and ``line_order``, which
    is the clock the ordering helpers fall back to when a caller does not
    pass one — the smart-alert pass among them.
    """
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    with (
        mock.patch(
            "werefa.queue.application.liveness_service.utcnow",
            return_value=moment,
        ),
        mock.patch(
            "werefa.queue.application.service.utcnow", return_value=moment
        ),
        mock.patch(
            "werefa.queue.application.line_order.utcnow", return_value=moment
        ),
    ):
        yield


def _owner_id(db: Session) -> str:
    u = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert u is not None
    return str(u.id)


def _line(client: TestClient, db: Session, headers: dict[str, str]) -> str:
    slug = f"live-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{API}/providers/",
        headers=headers,
        json={"slug": slug, "biz_name": "Liv", "owner_user_id": _owner_id(db)},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r2 = client.post(
        f"{API}/providers/{pid}/services/",
        headers=headers,
        json={"name": "Desk", "avg_duration_minutes": 10, "price": "1.00"},
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["id"]


def _customer(client: TestClient, db: Session) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    return user_authentication_headers(client=client, email=email, password=password)


def _join(client: TestClient, sid: str, headers: dict[str, str]) -> str:
    r = client.post(f"{API}/service-items/{sid}/join", headers=headers, json={})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _liveness(
    client: TestClient, sid: str, tid: str, headers: dict[str, str]
) -> dict:
    r = client.get(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _board(client: TestClient, sid: str, headers: dict[str, str]) -> list[dict]:
    r = client.get(f"{API}/service-items/{sid}/liveness/board", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _row(board: list[dict], tid: str) -> dict:
    match = [r for r in board if r["ticket_id"] == tid]
    assert match, f"ticket {tid} missing from board"
    return match[0]


def _flag(
    client: TestClient, sid: str, tid: str, staff: dict[str, str]
) -> dict:
    """Drive a ticket to ``flagged`` through the real two-stage path."""
    grace = settings.LIVENESS_GRACE_SECONDS
    _liveness(client, sid, tid, staff)
    for step in range(1, settings.LIVENESS_MISSES_BEFORE_FLAG + 1):
        with _at(grace * step + 60 * step):
            body = _liveness(client, sid, tid, staff)
    assert body["liveness_state"] == LivenessState.flagged.value, body
    return body


# --- baseline behaviour ----------------------------------------------------


def test_liveness_awaiting_when_in_top_k(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 3600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    assert (
        _liveness(client, sid, tid, cust)["liveness_state"]
        == LivenessState.awaiting.value
    )


def test_position_ping_sets_ok(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 3600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    p = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={"latitude": 9.0, "longitude": 38.7},
    )
    assert p.status_code == 200, p.text
    assert p.json()["liveness_state"] == LivenessState.ok.value
    assert _liveness(client, sid, tid, cust)["last_latitude"] == 9.0


def test_staff_can_read_customer_liveness(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    assert (
        _liveness(client, sid, tid, superuser_token_headers)["ticket_id"] == tid
    )


def test_stranger_cannot_ping_ticket(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)
    other = _customer(client, db)

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=other,
        json={"latitude": 1.0, "longitude": 2.0},
    )
    assert r.status_code == 403


# --- keeping false positives down ------------------------------------------


def test_one_missed_window_warns_and_only_the_second_flags(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """A single silent window is a nudge, not a verdict."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)

    with _at(120):
        first = _liveness(client, sid, tid, superuser_token_headers)
    assert first["liveness_state"] == LivenessState.awaiting.value
    assert first["misses"] == 1

    with _at(400):
        second = _liveness(client, sid, tid, superuser_token_headers)
    assert second["liveness_state"] == LivenessState.flagged.value
    assert second["misses"] == 2


def test_check_in_without_coordinates_buys_a_full_window(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """No GPS fix must still be a valid "I'm on my way".

    A denied location permission is the single most common honest reason
    to have no coordinates, and it earns exactly the same credit as a
    check-in that carried a fix — one clean grace window.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["liveness_state"] == LivenessState.ok.value

    # No coordinates were supplied, so no location was invented.
    pings = db.exec(
        select(PositionPing).where(PositionPing.ticket_id == uuid.UUID(tid))
    ).all()
    assert pings == []

    with _at(300):
        after = _liveness(client, sid, tid, superuser_token_headers)
    assert after["liveness_state"] == LivenessState.ok.value
    assert after["misses"] == 0
    assert after["recommended_action"] == LivenessAction.verify.value
    assert "not a no-show" in after["recommended_reason"]


def test_a_gps_less_check_in_is_worth_as_much_as_one_with_a_fix(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """Side by side: no fix, but confirmed, versus simply silent."""
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_GRACE_SECONDS = 600
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    confirmed = _customer(client, db)
    confirmed_tid = _join(client, sid, confirmed)
    silent = _customer(client, db)
    silent_tid = _join(client, sid, silent)

    def _check_in(at: float) -> None:
        with _at(at):
            r = client.post(
                f"{API}/service-items/{sid}/tickets/{confirmed_tid}/position",
                headers=confirmed,
                json={},
            )
        assert r.status_code == 200, r.text

    _board(client, sid, superuser_token_headers)
    # One customer keeps confirming without ever managing a fix; the other
    # says nothing at all. Only the second should end up flagged.
    _check_in(300)
    with _at(700):
        _board(client, sid, superuser_token_headers)
    _check_in(1000)
    with _at(1400):
        board = _board(client, sid, superuser_token_headers)

    assert (
        _row(board, silent_tid)["liveness_state"] == LivenessState.flagged.value
    )
    assert (
        _row(board, confirmed_tid)["liveness_state"] == LivenessState.ok.value
    )
    assert (
        _row(board, confirmed_tid)["recommended_action"]
        == LivenessAction.verify.value
    )


def test_half_supplied_coordinates_are_rejected(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={"latitude": 9.0},
    )
    assert r.status_code == 422


def test_an_app_left_open_at_home_still_gets_flagged(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """The absentee case that matters: polling, never confirming.

    The customer's app keeps reading their own ticket the whole time — the
    exact traffic a phone left on a kitchen table produces. It must not
    buy them a spot at the front of the line indefinitely.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 3600
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    for offset in (0, 120, 240, 360):
        with _at(offset):
            body = _liveness(client, sid, tid, cust)

    assert body["liveness_state"] == LivenessState.flagged.value
    assert body["recommended_action"] == LivenessAction.hold.value
    # The polling is still on the record — as evidence for staff, not as
    # an excuse.
    assert body["last_seen_at"] is not None
    assert "online but silent" in body["recommended_reason"]


def test_queue_snapshot_polling_does_not_hold_a_spot(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """Position polling is the app's own background chatter, not a check-in."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 3600
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)
    _liveness(client, sid, tid, superuser_token_headers)

    for offset in (120, 300):
        with _at(offset):
            snap = client.get(
                f"{API}/service-items/{sid}/tickets/{tid}/snapshot",
                headers=cust,
            )
            assert snap.status_code == 200, snap.text
            after = _liveness(client, sid, tid, superuser_token_headers)

    assert after["liveness_state"] == LivenessState.flagged.value
    assert after["last_seen_at"] is not None


def test_misses_accrue_across_windows_despite_polling(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """Polling must not quietly reset the counter between windows."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 3600
    settings.LIVENESS_MISSES_BEFORE_FLAG = 3
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, cust)
    seen = []
    for offset in (120, 300, 500):
        with _at(offset):
            seen.append(_liveness(client, sid, tid, cust)["misses"])

    assert seen == [1, 2, 3]


def test_priority_ticket_is_counted_in_the_top_k_window(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Top-K must mean "next to be called", not "lowest ticket number".

    Counting by ticket number asked the wrong people to check in as soon
    as a priority ticket existed — and left the person actually about to
    be called unasked.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    early = _customer(client, db)
    early_tid = _join(client, sid, early)
    late = _customer(client, db)
    late_tid = _join(client, sid, late)

    bump = client.patch(
        f"{API}/service-items/{sid}/tickets/{late_tid}/priority",
        headers=superuser_token_headers,
        json={"priority": 5},
    )
    assert bump.status_code == 200, bump.text

    board = _board(client, sid, superuser_token_headers)
    assert _row(board, late_tid)["position"] == 1
    # ...and the earlier ticket number is no longer treated as the front.
    assert [r["ticket_id"] for r in board] == [late_tid]
    assert early_tid not in {r["ticket_id"] for r in board}


# --- the next step: holding a spot -----------------------------------------


def test_hold_lets_the_line_move_past_without_touching_the_ticket(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The whole point: serve the next customer, keep the spot, no penalty."""
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 300
    sid = _line(client, db, superuser_token_headers)
    first = _customer(client, db)
    first_tid = _join(client, sid, first)
    second = _customer(client, db)
    second_tid = _join(client, sid, second)

    h = client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert h.status_code == 200, h.text
    assert h.json()["status"] == TicketStatus.waiting.value
    assert h.json()["hold_count"] == 1

    nxt = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["id"] == second_tid

    held = client.get(
        f"{API}/service-items/{sid}/tickets/{first_tid}/snapshot",
        headers=superuser_token_headers,
    )
    assert held.status_code == 200
    assert (
        _liveness(client, sid, first_tid, superuser_token_headers)["hold_until"]
        is not None
    )

    strikes = db.exec(
        select(UserStrike).where(UserStrike.ticket_id == uuid.UUID(first_tid))
    ).all()
    assert strikes == []


def test_a_check_in_during_a_hold_gives_the_spot_back_immediately(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Answering ends the park. That is the deal the hold message offers.

    A park exists because we could not reach this customer; the moment
    they confirm they are coming, its reason is gone. Making them sit out
    the rest of the timer anyway would punish the one person who did what
    we asked — and the hold notification tells them, in those words, that
    tapping "I'm on my way" keeps their place.
    """
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 300
    sid = _line(client, db, superuser_token_headers)
    first = _customer(client, db)
    first_tid = _join(client, sid, first)
    second = _customer(client, db)
    second_tid = _join(client, sid, second)
    third = _customer(client, db)
    third_tid = _join(client, sid, third)

    client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    # Serve past the park.
    served = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert served.json()["id"] == second_tid

    back = client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/position",
        headers=first,
        json={},
    )
    assert back.status_code == 200, back.text
    assert back.json()["liveness_state"] == LivenessState.ok.value
    assert back.json()["liveness_hold_until"] is None

    # They kept their place, so they are next — not the ticket behind them.
    nxt = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["id"] == first_tid
    assert nxt.json()["id"] != third_tid


def test_checking_back_in_does_not_refund_the_hold(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Unparking early must not hand out a fresh park.

    Otherwise a customer could check in, go quiet again, and collect an
    unlimited supply of holds — the exact indefinite shuffle the cap
    exists to prevent.
    """
    settings.LIVENESS_MAX_HOLDS = 1
    settings.LIVENESS_HOLD_SECONDS = 300
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    back = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={},
    )
    assert back.status_code == 200, back.text
    assert back.json()["liveness_hold_until"] is None
    assert back.json()["liveness_hold_count"] == 1

    again = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert again.status_code == 409


def test_a_vip_join_does_not_cancel_a_hold(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A park ends by its timer or a release — never by the line moving.

    The ticket falls out of the top-K watch window the moment a VIP is
    bumped past it, and the liveness bookkeeping goes with it. The hold
    must not: the customer was given a time, Call Next reads that column,
    and dropping it here silently handed their spot back to the counter
    that had just promised to keep it.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    first = _customer(client, db)
    first_tid = _join(client, sid, first)

    client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert (
        _liveness(client, sid, first_tid, superuser_token_headers)["hold_until"]
        is not None
    )

    late = _customer(client, db)
    late_tid = _join(client, sid, late)
    bump = client.patch(
        f"{API}/service-items/{sid}/tickets/{late_tid}/priority",
        headers=superuser_token_headers,
        json={"priority": 5},
    )
    assert bump.status_code == 200, bump.text

    # Board / liveness poll runs the sync that used to wipe the park.
    _board(client, sid, superuser_token_headers)
    assert (
        _liveness(client, sid, first_tid, superuser_token_headers)["hold_until"]
        is not None
    )

    # ...and the promise is kept where it counts: the VIP is served, the
    # parked customer is still passed over rather than called.
    nxt = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["id"] == late_tid


def test_a_held_spot_survives_the_line_moving_past_it(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Serving other customers must not quietly spend somebody's park."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    parked = _customer(client, db)
    parked_tid = _join(client, sid, parked)
    b = _customer(client, db)
    b_tid = _join(client, sid, b)
    c = _customer(client, db)
    c_tid = _join(client, sid, c)

    client.post(
        f"{API}/service-items/{sid}/tickets/{parked_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )

    served = []
    for _ in range(2):
        r = client.post(
            f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
        )
        assert r.status_code == 200, r.text
        served.append(r.json()["id"])

    assert served == [b_tid, c_tid]
    assert (
        _liveness(client, sid, parked_tid, superuser_token_headers)["hold_until"]
        is not None
    )


def test_the_customer_behind_a_park_is_the_one_asked_to_check_in(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Top-K follows Call Next, so a park ahead does not hide the next caller.

    With ``TOP_K = 1`` the parked ticket is skipped by Call Next, which
    makes the ticket behind it the one about to be served — and therefore
    the one we need a check-in from.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    parked = _customer(client, db)
    parked_tid = _join(client, sid, parked)
    behind = _customer(client, db)
    behind_tid = _join(client, sid, behind)

    client.post(
        f"{API}/service-items/{sid}/tickets/{parked_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )

    board = _board(client, sid, superuser_token_headers)
    ids = {r["ticket_id"] for r in board}
    # The parked spot stays visible however far the line has moved...
    assert parked_tid in ids
    # ...and the ticket Call Next will actually serve is being watched.
    assert behind_tid in ids
    assert (
        _row(board, behind_tid)["liveness_state"] == LivenessState.awaiting.value
    )


def test_hold_expiry_makes_the_ticket_callable_again(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 120
    sid = _line(client, db, superuser_token_headers)
    first = _customer(client, db)
    first_tid = _join(client, sid, first)
    second = _customer(client, db)
    second_tid = _join(client, sid, second)

    client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    served = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert served.json()["id"] == second_tid

    with _at(300):
        after = client.post(
            f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
        )
    assert after.status_code == 200, after.text
    assert after.json()["id"] == first_tid


def test_line_never_stalls_when_every_waiting_ticket_is_held(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A courtesy that idles the counter has stopped being a courtesy."""
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    only = _customer(client, db)
    only_tid = _join(client, sid, only)

    client.post(
        f"{API}/service-items/{sid}/tickets/{only_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    nxt = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert nxt.status_code == 200, nxt.text
    assert nxt.json()["id"] == only_tid
    assert nxt.json()["liveness_hold_until"] is None


def test_holds_are_capped_so_a_ticket_cannot_be_shuffled_forever(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_MAX_HOLDS = 1
    settings.LIVENESS_HOLD_SECONDS = 60
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    first = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert second.status_code == 409
    assert "no-show" in second.json()["detail"]


def test_releasing_a_hold_does_not_refund_it(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_MAX_HOLDS = 1
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    rel = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/release",
        headers=superuser_token_headers,
    )
    assert rel.status_code == 200, rel.text
    assert rel.json()["hold_until"] is None
    assert rel.json()["hold_count"] == 1

    again = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert again.status_code == 409


def test_hold_tells_the_customer_their_spot_is_safe(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    rows = db.exec(
        select(Notification)
        .where(Notification.ticket_id == uuid.UUID(tid))
        .where(Notification.kind == "liveness_hold")
    ).all()
    assert len(rows) == 1
    assert "keep your place" in rows[0].body


def test_only_staff_can_hold_a_spot(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=cust,
        json={},
    )
    assert r.status_code in (401, 403)


def test_a_ticket_being_served_cannot_be_held(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Once called, presence is a human judgement at the counter."""
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)
    client.post(f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers)

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 409


def test_walk_in_tickets_are_not_holdable(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    w = client.post(
        f"{API}/service-items/{sid}/walk-in",
        headers=superuser_token_headers,
        json={"guest_name": "Walk In"},
    )
    assert w.status_code == 200, w.text

    r = client.post(
        f"{API}/service-items/{sid}/tickets/{w.json()['id']}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 400


# --- the staff board -------------------------------------------------------


def test_board_turns_a_flag_into_a_next_step(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.LIVENESS_MAX_HOLDS = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _flag(client, sid, tid, superuser_token_headers)

    row = _row(_board(client, sid, superuser_token_headers), tid)
    assert row["liveness_state"] == LivenessState.flagged.value
    assert row["recommended_action"] == LivenessAction.hold.value
    assert row["can_hold"] is True
    assert row["recommended_reason"]


def test_an_app_waking_up_mid_hold_does_not_end_the_hold(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Background traffic during a hold changes nothing.

    Handing the spot back to a phone that resumed polling — while its
    owner has still told us nothing — is the soft failure the hold model
    exists to avoid. Nothing but the timer or an explicit release ends a
    park; see ``test_explicit_check_in_keeps_staff_hold_until_timer_or_release``
    for the stronger version of the same rule.
    """
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 600
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    snap = client.get(
        f"{API}/service-items/{sid}/tickets/{tid}/snapshot", headers=cust
    )
    assert snap.status_code == 200, snap.text

    row = _row(_board(client, sid, superuser_token_headers), tid)
    assert row["recommended_action"] == LivenessAction.hold.value
    assert row["hold_until"] is not None


def test_the_board_shows_a_checked_in_customer_as_callable_again(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The board must agree with Call Next about who is parked.

    A check-in unparks the spot, so the row staff read has to stop saying
    "keep serving others" — that was the mismatch that had a board showing
    a customer restored while the counter kept skipping them.
    """
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_HOLD_SECONDS = 600
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={"latitude": 9.0, "longitude": 38.7},
    )

    row = _row(_board(client, sid, superuser_token_headers), tid)
    assert row["hold_until"] is None
    assert row["liveness_state"] == LivenessState.ok.value
    assert row["recommended_action"] == LivenessAction.proceed.value
    assert row["hold_count"] == 1  # spent, and still on the record


def test_a_check_in_inside_a_park_buys_a_clean_window(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Unparking hands back a full grace window, not the park's leftovers.

    The customer who answered is now an ordinary waiting ticket again: no
    misses on the record, a fresh window, and — until that window runs
    out — nothing for staff to do but call them.
    """
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_GRACE_SECONDS = 600
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.LIVENESS_HOLD_SECONDS = 60
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _flag_free = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    assert _flag_free.status_code == 200, _flag_free.text
    checked_in = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={},
    )
    assert checked_in.status_code == 200, checked_in.text

    # Well past the 60s park the check-in cancelled, still inside the
    # 600s window it bought.
    with _at(200):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] == LivenessState.ok.value
    assert body["misses"] == 0
    assert body["hold_until"] is None


def test_releasing_a_park_does_not_immediately_flag_the_customer(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The window ran to the end of the park, so a release must re-arm it.

    Otherwise staff releasing a hold early hands the customer a window
    that was already spent, and the next sync scores a miss for silence
    during minutes they were told to sit out.
    """
    settings.LIVENESS_TOP_K = 3
    settings.LIVENESS_GRACE_SECONDS = 600
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    rel = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/release",
        headers=superuser_token_headers,
    )
    assert rel.status_code == 200, rel.text

    body = _liveness(client, sid, tid, superuser_token_headers)
    assert body["hold_until"] is None
    assert body["misses"] == 0
    assert body["liveness_state"] == LivenessState.awaiting.value
    # Released spots are callable again straight away.
    nxt = client.post(
        f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers
    )
    assert nxt.json()["id"] == tid


def test_board_keeps_showing_a_held_ticket_pushed_out_of_top_k(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A parked spot must never quietly fall off the board."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_HOLD_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    first = _customer(client, db)
    first_tid = _join(client, sid, first)
    second = _customer(client, db)
    second_tid = _join(client, sid, second)

    client.post(
        f"{API}/service-items/{sid}/tickets/{first_tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    client.post(f"{API}/service-items/{sid}/call-next", headers=superuser_token_headers)

    board = _board(client, sid, superuser_token_headers)
    ids = {r["ticket_id"] for r in board}
    assert first_tid in ids
    assert second_tid not in ids  # being served, no longer a liveness question


def test_board_is_staff_only(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    _join(client, sid, cust)

    r = client.get(f"{API}/service-items/{sid}/liveness/board", headers=cust)
    assert r.status_code in (401, 403)


def test_liveness_never_records_a_strike_on_its_own(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """Flag, hold, expire — none of it may penalise the customer.

    The only path to a strike stays: staff calls them, they do not appear,
    staff marks no-show.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_ACTIVITY_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.LIVENESS_HOLD_SECONDS = 60
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _flag(client, sid, tid, superuser_token_headers)
    client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/liveness/hold",
        headers=superuser_token_headers,
        json={},
    )
    with _at(600):
        _board(client, sid, superuser_token_headers)

    strikes = db.exec(
        select(UserStrike).where(UserStrike.ticket_id == uuid.UUID(tid))
    ).all()
    assert strikes == []
    ticket = _liveness(client, sid, tid, superuser_token_headers)
    assert ticket["liveness_state"] != TicketStatus.no_show.value


# --- silence only counts if they were asked --------------------------------


def _prompts(db: Session, tid: str) -> list[Notification]:
    """The prompts this ticket was sent, newest first."""
    rows = db.exec(
        select(Notification)
        .where(Notification.ticket_id == uuid.UUID(tid))
        .where(
            col(Notification.kind).in_(
                [k.value for k in liveness_service.PROMPT_KINDS]
            )
        )
    ).all()
    return sorted(rows, key=lambda r: r.created_at, reverse=True)  # type: ignore[arg-type,return-value]


def _record_reach(
    db: Session, tid: str, *, channel: NotificationChannel, status: NotificationStatus
) -> None:
    """Rewrite the latest prompt's ledger row as the delivery path would.

    Standing in for the delivery worker plus a carrier receipt, so this
    test can pin the liveness consequence without a Twilio account.
    """
    rows = _prompts(db, tid)
    assert rows, "expected a liveness prompt to have been dispatched"
    rows[0].channel = channel.value
    rows[0].status = status.value
    db.add(rows[0])
    db.commit()


def test_an_undelivered_prompt_never_flags_the_customer(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The unfairness this closes.

    Two silent windows used to flag, and a flag is what sends staff to
    call the customer — which is the only path that can end in a no-show
    strike. When the carrier rejected every text we sent, that whole
    chain was set off by our delivery failure and charged to them.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    for offset in (120, 400, 700):
        with _at(offset):
            body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] == LivenessState.awaiting.value
    assert body["misses"] == 0


def test_a_confirmed_prompt_still_flags_a_silent_customer(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    prompts_delivered: None,
) -> None:
    """The control. Leniency is bought with proof of *our* failure only."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.delivered,
    )

    with _at(120):
        _liveness(client, sid, tid, superuser_token_headers)
    with _at(400):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] == LivenessState.flagged.value


def test_an_undelivered_prompt_is_not_shouted_down_the_same_dead_channel(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A ``failed`` row means every channel was already exhausted.

    Repeating the nudge each window would be noise with a gateway bill
    attached. The hold notification is the exception and is not a repeat:
    it says something new ("your spot is being kept"), and it goes out
    once per park rather than once per poll.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    for offset in (120, 400, 700, 1000):
        with _at(offset):
            _liveness(client, sid, tid, superuser_token_headers)

    kinds = [r.kind for r in _prompts(db, tid)]
    assert kinds.count(NotificationKind.liveness_stale.value) == 0
    # One per park, capped by LIVENESS_MAX_HOLDS — not one per poll.
    assert (
        0
        < kinds.count(NotificationKind.liveness_hold.value)
        <= settings.LIVENESS_MAX_HOLDS
    )


def test_an_unreachable_spot_is_parked_without_waiting_for_staff(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The line must not stall on a number we cannot text.

    Surfacing "we could not reach them" on the board and stopping there
    left the customer at the head of the queue until somebody looked —
    and the line's next move was Call Next reaching them anyway, nobody
    answering, and a no-show against someone never spoken to.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    with _at(120):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["hold_until"] is not None
    assert body["hold_count"] == 1
    # A park, not a penalty: still waiting, still no strike.
    assert body["liveness_state"] == LivenessState.awaiting.value
    assert body["misses"] == 0


def test_the_board_says_the_park_is_ours_not_theirs(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """"Until they check in" is the wrong instruction for a customer who
    was never asked — it invites waiting for an answer that cannot come."""
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    with _at(120):
        row = _row(_board(client, sid, superuser_token_headers), tid)

    assert row["warning_reach"] == NotificationReach.not_reached.value
    assert row["recommended_action"] == LivenessAction.hold.value
    assert "could not get a message" in row["recommended_reason"]
    assert "call them" in row["recommended_reason"]


def test_the_hold_we_granted_does_not_launder_the_reach(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The subtlest way this could have gone wrong.

    Parking an unreachable customer sends them a "your spot is held"
    notification, which is itself a prompt and lands 'delivered' on the
    websocket channel. Taking the newest prompt row unconditionally would
    let the hold we granted *because* we could not reach them flip the
    ticket back to "we do not know" — and the next window would flag them
    on exactly the silence the hold existed to excuse.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.LIVENESS_HOLD_SECONDS = 60
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    with _at(120):
        _liveness(client, sid, tid, superuser_token_headers)
    # Well past the first park's expiry, so the window is judged again.
    with _at(400):
        body = _liveness(client, sid, tid, superuser_token_headers)
        row = _row(_board(client, sid, superuser_token_headers), tid)

    assert row["warning_reach"] == NotificationReach.not_reached.value
    assert body["liveness_state"] != LivenessState.flagged.value
    assert body["misses"] == 0


def test_auto_holds_are_capped_and_then_it_is_a_humans_problem(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A line cannot step over one ticket forever.

    Once the holds are spent the honest next step is a person calling
    them — the only route that can end in a strike, and the only one a
    timer must never take on its own.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.LIVENESS_HOLD_SECONDS = 60
    settings.LIVENESS_MAX_HOLDS = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    for offset in (120, 400, 700, 1000, 1300):
        with _at(offset):
            body = _liveness(client, sid, tid, superuser_token_headers)
            row = _row(_board(client, sid, superuser_token_headers), tid)

    assert body["hold_count"] == settings.LIVENESS_MAX_HOLDS
    assert row["recommended_action"] == LivenessAction.proceed.value
    assert "call them" in row["recommended_reason"]
    # Still no strike, and still waiting — the cap ends the automation,
    # not the customer's claim to their place.
    assert body["liveness_state"] != LivenessState.flagged.value
    strikes = db.exec(select(UserStrike)).all()
    assert all(s.ticket_id != uuid.UUID(tid) for s in strikes)


def test_auto_hold_can_be_switched_off(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_AUTO_HOLD_UNREACHABLE = False
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    with _at(120):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["hold_until"] is None
    # The leniency is unaffected by the lever; only the parking is.
    assert body["misses"] == 0
    assert body["liveness_state"] != LivenessState.flagged.value


def test_a_receipt_that_never_arrives_stops_excusing_and_stops_blaming(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A row parked at 'sent' forever is not an open question.

    Twilio took the message and never reported back — most often a
    status-callback URL that does not resolve. Treating that as "we do
    not know" indefinitely means one misconfigured webhook quietly
    restores the old unfairness for everybody.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    settings.NOTIFICATION_RECEIPT_GRACE_SECONDS = 30.0
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db, tid, channel=NotificationChannel.sms, status=NotificationStatus.sent
    )

    with _at(120):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] != LivenessState.flagged.value
    assert body["misses"] == 0
    assert body["hold_until"] is not None


def test_an_alert_that_only_reached_the_logger_backstop_is_not_evidence(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The commonest case, and the one that looked like success.

    ``_user_prefs`` appends ``logger`` to every preference list and
    ``LoggerNotifier`` never fails, so a customer with no reachable
    channel produces a ledger full of 'delivered' rows — and was flagged
    for ignoring prompts that were never sent anywhere.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.logger,
        status=NotificationStatus.delivered,
    )

    with _at(120):
        _liveness(client, sid, tid, superuser_token_headers)
    with _at(400):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] == LivenessState.awaiting.value
    assert body["misses"] == 0


def test_a_prompt_still_awaiting_its_receipt_behaves_exactly_as_before(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ignorance is not proof.

    A gateway accepted the text and has not reported back *yet*. Treating
    that as an excuse would make every slow carrier a way to be
    unflaggable, so a genuinely pending row must behave exactly as it did
    before any of this existed.

    The reach is pinned rather than written into the ledger because every
    window dispatches a fresh prompt, and in this environment each of
    those lands on the logger backstop — a *decided* ``not_reached`` that
    would correctly outrank a stale pending row and quietly turn this into
    a different test. What happens once the wait itself lapses is
    ``test_a_receipt_that_never_arrives_stops_excusing_and_stops_blaming``.
    """
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 60
    settings.LIVENESS_MISSES_BEFORE_FLAG = 2
    _pin_prompt_reach(
        monkeypatch,
        NotificationReach.unconfirmed,
        channel=NotificationChannel.sms,
        status=NotificationStatus.sent,
    )
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)

    with _at(120):
        _liveness(client, sid, tid, superuser_token_headers)
    with _at(400):
        body = _liveness(client, sid, tid, superuser_token_headers)

    assert body["liveness_state"] == LivenessState.flagged.value


def test_a_customer_who_checks_in_is_fine_however_the_prompt_fared(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    settings.LIVENESS_TOP_K = 1
    settings.LIVENESS_GRACE_SECONDS = 600
    sid = _line(client, db, superuser_token_headers)
    cust = _customer(client, db)
    tid = _join(client, sid, cust)

    _liveness(client, sid, tid, superuser_token_headers)
    _record_reach(
        db,
        tid,
        channel=NotificationChannel.sms,
        status=NotificationStatus.failed,
    )

    p = client.post(
        f"{API}/service-items/{sid}/tickets/{tid}/position",
        headers=cust,
        json={"latitude": 9.0, "longitude": 38.7},
    )
    assert p.status_code == 200, p.text

    row = _row(_board(client, sid, superuser_token_headers), tid)
    assert row["liveness_state"] == LivenessState.ok.value
    assert row["recommended_action"] == LivenessAction.proceed.value
    assert "Checked in with location" in row["recommended_reason"]
