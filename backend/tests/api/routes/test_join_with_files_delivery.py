"""``POST /service-items/{id}/join-with-files`` no longer waits on the SMS
gateway (FR-07).

This is the route the whole change is about. It is the only ``async def``
endpoint that triggers ``dispatch``, so a blocking send inside it did not
just slow one request — it held the event loop and stalled every other
connected client for up to ``SMS_TIMEOUT_SECONDS``.

Every test here is parametrised over ``NOTIFICATION_DELIVERY_ASYNC``, and
asserts the *opposite* result when it is off. That flag is the production
rollback lever, so it doubles as a control: without it these would be
timing assertions that pass whether or not the fix works.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.main import app
from werefa.notifications.infrastructure.sms.base import SmsMessage, SmsResult
from werefa.shared.enums import NotificationStatus
from werefa.shared.models import (
    Notification,
    ServiceItem,
    UserCreate,
)

# Long enough that a stalled loop is unmistakable, short enough to keep
# the suite quick. The assertions use generous margins either side.
GATEWAY_SECONDS = 1.5


@dataclass
class _SlowGateway:
    """A gateway that takes its time, like a real one having a bad day."""

    name: str = "slow-fake"
    delay: float = GATEWAY_SECONDS
    sent: list[SmsMessage] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def configured(self) -> bool:
        return True

    def send(self, message: SmsMessage) -> SmsResult:
        time.sleep(self.delay)
        with self._lock:
            self.sent.append(message)
        return SmsResult.sent(provider=self.name, provider_message_id="slow-1")


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Generator[_SlowGateway, None, None]:
    from werefa.notifications.application import service as notifications_service
    from werefa.notifications.infrastructure.sms import factory

    provider = _SlowGateway()
    monkeypatch.setattr(factory, "_provider", provider)
    # Rebuild the registry so the shipping SmsNotifier picks the fake up.
    notifications_service.set_registry(None)
    # Keep SMTP out of it: the email copy is a second remote channel and
    # would blur which send the timings are measuring.
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    yield provider
    notifications_service.set_registry(None)


@pytest.fixture
def no_cloudinary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Join documents are stored remotely; that is not what is under test."""
    from werefa.core import cloudinary_storage

    def _fake_upload(*, data: bytes, filename: str, folder: str) -> object:
        assert data, "an empty upload would have been rejected earlier"
        return cloudinary_storage.StoredFile(
            public_id=f"{folder}/{filename}-{uuid.uuid4().hex}",
            resource_type="image",
            secure_url="https://example.invalid/doc.png",
        )

    monkeypatch.setattr(cloudinary_storage, "upload_bytes", _fake_upload)


def _line_requiring_documents(
    *, client: TestClient, db: Session, staff_headers: dict[str, str]
) -> str:
    staff = identity_repo.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert staff is not None
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=staff_headers,
        json={
            "slug": f"docs-{uuid.uuid4().hex[:8]}",
            "biz_name": "Docs Required",
            "owner_user_id": str(staff.id),
        },
    )
    assert r.status_code == 200, r.text
    provider_id = r.json()["id"]

    r2 = client.post(
        f"{settings.API_V1_STR}/providers/{provider_id}/services/",
        headers=staff_headers,
        json={"name": "Line", "avg_duration_minutes": 10, "price": "1.00"},
    )
    assert r2.status_code == 200, r2.text
    service_id = r2.json()["id"]

    svc = db.get(ServiceItem, uuid.UUID(service_id))
    assert svc is not None
    svc.requires_join_documents = True
    svc.join_document_requirements = [{"label": "ID card", "kind": "image"}]
    db.add(svc)
    db.commit()
    return service_id


def _customer_who_wants_sms(*, client: TestClient, db: Session) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    user = identity_repo.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    user.phone_number = "+251911234567"
    # SMS first, logger as the backstop — the ordering the change is about.
    user.notification_prefs = ["sms", "logger"]
    db.add(user)
    db.commit()
    return user_authentication_headers(client=client, email=email, password=password)


def _documents() -> dict[str, tuple[str, bytes, str]]:
    return {"documents": ("id.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}


def _ledger_rows(db: Session) -> list[Notification]:
    db.expire_all()
    return list(db.exec(select(Notification)).all())


@pytest.fixture
def async_delivery(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> bool:
    enabled: bool = request.param
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", enabled)
    return enabled


@pytest.mark.parametrize(
    "async_delivery", [True, False], ids=["deferred", "inline"], indirect=True
)
def test_the_response_does_not_wait_for_the_sms_gateway(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    gateway: _SlowGateway,
    no_cloudinary: None,
    async_delivery: bool,
) -> None:
    """The headline fix, and its control.

    With delivery deferred the customer gets their ticket back immediately
    and the text goes out afterwards; with it inline they wait for Twilio.
    """
    from werefa.notifications.application import service as notifications_service

    service_id = _line_requiring_documents(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    headers = _customer_who_wants_sms(client=client, db=db)

    started = time.monotonic()
    r = client.post(
        f"{settings.API_V1_STR}/service-items/{service_id}/join-with-files",
        headers=headers,
        files=_documents(),
    )
    elapsed = time.monotonic() - started

    assert r.status_code == 200, r.text

    if not async_delivery:
        assert elapsed >= GATEWAY_SECONDS, (
            "control failed: inline dispatch should make the caller wait for "
            "the gateway, so the deferred case above is not proving anything"
        )
        return

    assert elapsed < GATEWAY_SECONDS, (
        f"response took {elapsed:.2f}s — the gateway is still on the request path"
    )

    # Deferred, not dropped: the row starts queued and the worker finishes
    # the job and resolves it.
    queued = _ledger_rows(db)
    assert any(n.status == NotificationStatus.queued.value for n in queued)

    assert notifications_service.get_delivery_queue().wait_idle(timeout=15.0)
    # Joining also syncs liveness, which can fire its own alert — what
    # matters is that every one of them reached the gateway afterwards.
    assert gateway.sent, "the text was deferred and then never sent"
    assert {m.to for m in gateway.sent} == {"+251911234567"}

    resolved = _ledger_rows(db)
    sms_rows = [n for n in resolved if n.channel == "sms"]
    assert sms_rows, "the ledger should still name sms as the winning channel"
    assert all(n.status == NotificationStatus.delivered.value for n in sms_rows), (
        "the worker left a row unresolved"
    )
    assert len(gateway.sent) == len(sms_rows)


@pytest.fixture
def anyio_backend() -> str:
    # trio is not a dependency; pin the plugin to asyncio.
    return "asyncio"


async def _worst_tick_gap(coro: object, *, interval: float = 0.05) -> float:
    """Run ``coro``, returning the longest the event loop went unserviced.

    A heartbeat rather than a second request, because a blocked loop also
    blocks the timer that would schedule the probe — measuring *after*
    the stall reports a healthy loop no matter how long it was stuck.
    The gap between successive ticks cannot be faked that way: whatever
    holds the loop shows up as one oversized interval.
    """
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(interval)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    try:
        await coro  # type: ignore[misc]
    finally:
        stop.set()
        await beat

    return max(gaps) if gaps else 0.0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "async_delivery", [True, False], ids=["deferred", "inline"], indirect=True
)
async def test_a_slow_gateway_does_not_stall_the_event_loop(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    gateway: _SlowGateway,
    no_cloudinary: None,
    async_delivery: bool,
) -> None:
    """The reason this route was singled out.

    Sync routes run in the threadpool, so a slow send there costs one
    request. ``join-with-files`` is ``async def``, so the send ran *on*
    the loop — every other connected client waited for Twilio too. The
    heartbeat below shares that loop and measures exactly that.
    """
    service_id = _line_requiring_documents(
        client=client, db=db, staff_headers=superuser_token_headers
    )
    headers = _customer_who_wants_sms(client=client, db=db)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        responses: list[httpx.Response] = []

        async def join() -> None:
            responses.append(
                await ac.post(
                    f"{settings.API_V1_STR}/service-items/{service_id}"
                    "/join-with-files",
                    headers=headers,
                    files=_documents(),
                    timeout=30.0,
                )
            )

        worst_gap = await _worst_tick_gap(join())

    assert responses[0].status_code == 200, responses[0].text

    if not async_delivery:
        assert worst_gap >= GATEWAY_SECONDS / 2, (
            "control failed: an inline send in an async route should block the "
            "loop, so the deferred case is not proving anything"
        )
        return

    assert worst_gap < GATEWAY_SECONDS / 2, (
        f"the loop went {worst_gap:.2f}s without a tick — the SMS send is "
        "still holding it"
    )
