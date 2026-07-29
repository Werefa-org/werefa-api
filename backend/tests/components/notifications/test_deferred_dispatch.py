"""Dispatch hands remote channels to the delivery worker (FR-07).

Two halves, because the change split one synchronous decision in two:

* **Deferral** — what ``dispatch`` does on the request thread. It must
  write a ``queued`` ledger row and hand over *without* touching the
  gateway, and it must still take the old inline path when the channel
  is local, unconfigured, or the feature is switched off.
* **Resolution** — what ``deliver_job`` does on the worker. It owns the
  channel fall-through that used to live in the dispatch loop, and it is
  the only thing that ever writes a final status onto a ``queued`` row.

The sessions here are fakes on purpose. ``dispatch``'s session has no
``.info``, which is the documented signal for "no transaction to wait
on, hand over now" — that is what makes these assertions synchronous.
The transactional hand-off itself is tested against a real session at
the bottom of the file.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest

from werefa.core.config import settings
from werefa.notifications.application import service as notifications_service
from werefa.notifications.domain.retry import RetryPolicy
from werefa.notifications.infrastructure.delivery import (
    DeliveryJob,
    InlineDeliveryQueue,
)
from werefa.notifications.notifier import (
    DeliveryOutcome,
    NotificationPayload,
)
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from werefa.shared.models import Notification, User

FAST = RetryPolicy(max_attempts=3, base_seconds=0.0001, max_seconds=0.001, jitter_ratio=0.0)


# --- doubles -------------------------------------------------------------


@dataclass
class _LocalNotifier:
    """An in-process channel: no ``ready``, no ``deliver``, never deferred."""

    channel: NotificationChannel
    deliverable: bool = True
    calls: list[NotificationPayload] = field(default_factory=list)

    def send(self, *, user: Any, payload: NotificationPayload) -> bool:
        self.calls.append(payload)
        return self.deliverable


@dataclass
class _RemoteNotifier:
    """Stands in for SmsNotifier / EmailNotifier: advertises ``ready`` and
    answers the tri-state the worker needs."""

    channel: NotificationChannel
    ready: bool = True
    outcomes: list[DeliveryOutcome] = field(
        default_factory=lambda: [DeliveryOutcome.delivered]
    )
    calls: list[NotificationPayload] = field(default_factory=list)

    def deliver(self, *, user: Any, payload: NotificationPayload) -> DeliveryOutcome:
        if not self.ready:
            # Matches SmsNotifier/EmailNotifier: an unconfigured channel
            # reports permanent without recording a call.
            return DeliveryOutcome.permanent
        self.calls.append(payload)
        index = min(len(self.calls) - 1, len(self.outcomes) - 1)
        return self.outcomes[index]

    def send(self, *, user: Any, payload: NotificationPayload) -> bool:
        return self.deliver(user=user, payload=payload) is DeliveryOutcome.delivered


@dataclass
class _DispatchSession:
    """The request's session. No ``.info``, so hand-off is immediate."""

    persisted: list[Any] = field(default_factory=list)

    def add(self, obj: Any) -> None:
        self.persisted.append(obj)

    def flush(self) -> None:
        return None

    def refresh(self, _obj: Any) -> None:
        return None


class _WorkerSession:
    """The session ``deliver_job`` opens for itself, backed by dicts."""

    def __init__(self, users: dict[uuid.UUID, Any], rows: list[Any]) -> None:
        self._users = users
        self._rows = rows
        self.commits = 0

    def __enter__(self) -> _WorkerSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def get(self, model: type, pk: uuid.UUID) -> Any:
        pool = self._users if model is User else {r.id: r for r in self._rows}
        return pool.get(pk)

    def add(self, _obj: Any) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class _CaptureQueue:
    """Records hand-offs without running them — proves dispatch defers."""

    def __init__(self) -> None:
        self.jobs: list[DeliveryJob] = []
        self.deferred: list[DeliveryJob] = []

    def submit(self, job: DeliveryJob) -> bool:
        self.jobs.append(job)
        return True

    def defer(self, job: DeliveryJob) -> bool:
        self.deferred.append(job)
        return True

    def start(self) -> None:
        return None

    def stop(self, *, timeout: float = 5.0) -> None:
        return None


class _FullQueue(_CaptureQueue):
    """Always at capacity, but still parks what it refuses."""

    def submit(self, job: DeliveryJob) -> bool:
        self.jobs.append(job)
        return False


class _FullQueueNoParking(_FullQueue):
    """At capacity *and* out of parking space — the send is truly lost."""

    def defer(self, job: DeliveryJob) -> bool:
        self.deferred.append(job)
        return False


@dataclass
class _FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    is_active: bool = True
    email: str | None = "customer@example.com"
    notification_prefs: list[str] | None = None


# --- harness -------------------------------------------------------------


@dataclass
class _Harness:
    user: _FakeUser
    session: _DispatchSession
    rows: list[Any]
    users: dict[uuid.UUID, Any]

    def dispatch(
        self, kind: NotificationKind = NotificationKind.you_are_next
    ) -> Notification:
        row = notifications_service.dispatch(
            self.session,  # type: ignore[arg-type]
            user=self.user,  # type: ignore[arg-type]
            payload=NotificationPayload(
                kind=kind, body="you are next", ticket_id=uuid.uuid4()
            ),
        )
        assert row is not None
        return row


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Generator[_Harness, None, None]:
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", True)
    # Off unless a test asks for it, so the email-copy path cannot fire
    # from whatever happens to be in the developer's .env.
    monkeypatch.setattr(settings, "SMTP_HOST", None)

    user = _FakeUser()
    rows: list[Any] = []
    session = _DispatchSession()
    users = {user.id: user}

    # ``dispatch`` persists into ``session``; the worker must find the same
    # row through its own session, exactly as it does against the database.
    notifications_service.set_delivery_session_factory(
        lambda: _WorkerSession(users, session.persisted)  # type: ignore[arg-type,return-value]
    )
    yield _Harness(user=user, session=session, rows=rows, users=users)

    notifications_service.set_registry(None)
    notifications_service.set_delivery_queue(None)
    notifications_service.set_delivery_session_factory(None)


def _registry(*notifiers: Any) -> None:
    notifications_service.set_registry({n.channel: n for n in notifiers})  # type: ignore[arg-type]


def _capture() -> _CaptureQueue:
    queue = _CaptureQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    return queue


def _inline() -> InlineDeliveryQueue:
    queue = InlineDeliveryQueue(
        notifications_service.deliver_job, policy=FAST, sleeper=lambda _: None
    )
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    return queue


# --- deferral: what the request thread does ------------------------------


def test_sms_is_queued_and_the_gateway_is_not_touched_during_dispatch(
    harness: _Harness,
) -> None:
    """The regression this whole change is about: the response no longer
    waits on a provider."""
    sms = _RemoteNotifier(NotificationChannel.sms)
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    queue = _capture()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert sms.calls == []
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.queued.value
    assert len(queue.jobs) == 1


def test_the_queued_job_carries_the_untried_preferences(
    harness: _Harness,
) -> None:
    """Fall-through has to survive the hand-off — only the worker will
    know whether SMS worked."""
    _registry(
        _RemoteNotifier(NotificationChannel.sms),
        _LocalNotifier(NotificationChannel.push),
        _LocalNotifier(NotificationChannel.logger),
    )
    queue = _capture()
    harness.user.notification_prefs = ["sms", "push", "logger"]

    row = harness.dispatch()

    job = queue.jobs[0]
    assert job.channel == NotificationChannel.sms
    assert job.notification_id == row.id
    assert job.fallback_channels == (
        NotificationChannel.push,
        NotificationChannel.logger,
    )


def test_a_local_channel_that_delivers_first_never_reaches_sms(
    harness: _Harness,
) -> None:
    """In-process channels are still resolved inline, so the common case
    keeps a fully-decided ledger row and costs nothing extra."""
    ws = _LocalNotifier(NotificationChannel.websocket)
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(ws, sms, _LocalNotifier(NotificationChannel.logger))
    queue = _capture()
    harness.user.notification_prefs = ["websocket", "sms", "logger"]

    row = harness.dispatch()

    assert row.status == NotificationStatus.delivered.value
    assert row.channel == NotificationChannel.websocket.value
    assert queue.jobs == []


def test_an_unconfigured_gateway_falls_through_inline_as_before(
    harness: _Harness,
) -> None:
    """``SMS_PROVIDER=disabled`` must not start writing ``queued`` rows it
    would only walk back a moment later."""
    sms = _RemoteNotifier(NotificationChannel.sms, ready=False)
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    queue = _capture()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert queue.jobs == []
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_switching_the_feature_off_restores_fully_inline_dispatch(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production rollback lever."""
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", False)
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    queue = _capture()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert len(sms.calls) == 1
    assert queue.jobs == []
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value


def test_the_email_copy_is_queued_without_a_ledger_row_of_its_own(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SMTP was the other blocking send on the request path. The copy has
    never owned a row, so the worker has nothing to resolve."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "queue@example.com")
    email = _RemoteNotifier(NotificationChannel.email)
    _registry(
        _LocalNotifier(NotificationChannel.websocket),
        email,
        _LocalNotifier(NotificationChannel.logger),
    )
    queue = _capture()
    harness.user.notification_prefs = ["websocket", "email", "logger"]

    row = harness.dispatch(NotificationKind.you_are_next)

    assert email.calls == []
    assert row.channel == NotificationChannel.websocket.value
    assert len(queue.jobs) == 1
    assert queue.jobs[0].channel == NotificationChannel.email
    assert queue.jobs[0].notification_id is None
    assert queue.jobs[0].fallback_channels == ()


def test_a_full_queue_sheds_the_remote_channel_instead_of_the_alert(
    harness: _Harness,
) -> None:
    """Overflow means the gateway is wedged. Taking the next preference
    keeps the ledger honest rather than dropping the alert."""
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    notifications_service.set_delivery_queue(_FullQueue())  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert sms.calls == []
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_full_queue_never_calls_a_provider_on_the_request_thread(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overflow path must not undo the whole change.

    Falling through to the next *preference* is only safe while that
    preference is in-process. With prefs like ``["sms", "email", ...]``
    an unguarded fall-through would make a blocking SMTP call right here
    on the request thread — the exact stall the queue exists to remove.
    Remote fallbacks are skipped, not sent.
    """
    # Every kind is normally in EMAIL_COPY_KINDS, which lifts email out of
    # the preference list entirely; empty it so email is a real fallback.
    monkeypatch.setattr(notifications_service, "EMAIL_COPY_KINDS", frozenset())
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "queue@example.com")

    sms = _RemoteNotifier(NotificationChannel.sms)
    email = _RemoteNotifier(NotificationChannel.email)
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, email, logger_n)
    notifications_service.set_delivery_queue(_FullQueue())  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "email", "logger"]

    row = harness.dispatch()

    assert sms.calls == [], "the wedged gateway was called on the request thread"
    assert email.calls == [], "SMTP was called on the request thread"
    assert len(logger_n.calls) == 1
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_full_queue_records_failed_when_only_remote_channels_remain(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing local to shed onto, the alert is lost — but recorded.

    A ``failed`` row plus the logged overflow is the honest outcome;
    blocking the caller on the second gateway would not be.
    """
    monkeypatch.setattr(notifications_service, "EMAIL_COPY_KINDS", frozenset())
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "queue@example.com")

    sms = _RemoteNotifier(NotificationChannel.sms)
    email = _RemoteNotifier(NotificationChannel.email)
    # No logger entry, so the backstop ``_user_prefs`` appends resolves to
    # nothing and only remote channels are left.
    _registry(sms, email)
    notifications_service.set_delivery_queue(_FullQueue())  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "email"]

    row = harness.dispatch()

    assert sms.calls == []
    assert email.calls == []
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.failed.value


def test_a_shed_send_is_parked_for_when_capacity_returns(
    harness: _Harness,
) -> None:
    """Shedding onto ``logger`` is a floor, not a verdict.

    The customer chose SMS; losing it permanently because of a momentary
    burst would throw away the real channel. The job is parked so it goes
    out once the gateway drains.
    """
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    queue = _FullQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert sms.calls == [], "parking must not send anything itself"
    assert len(queue.deferred) == 1
    parked = queue.deferred[0]
    assert parked.channel == NotificationChannel.sms
    assert parked.notification_id == row.id
    # The fall-through already happened, so a failed retry must not
    # deliver to logger a second time.
    assert parked.fallback_channels == ()
    assert parked.upgrade_only is True


def test_a_parked_send_that_lands_later_upgrades_the_row(
    harness: _Harness,
) -> None:
    """The ledger ends up naming the channel the user actually ranked
    first, exactly as it would have without the burst."""
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    queue = _FullQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()
    assert row.channel == NotificationChannel.logger.value

    # A worker promotes the parked job once there is room.
    notifications_service.deliver_job(queue.deferred[0])

    assert len(sms.calls) == 1
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value


def test_a_parked_send_that_fails_leaves_the_fallback_delivery_standing(
    harness: _Harness,
) -> None:
    """The retry is a bonus attempt. Marking the row ``failed`` would
    erase a delivery that really happened on the fallback."""
    sms = _RemoteNotifier(
        NotificationChannel.sms, outcomes=[DeliveryOutcome.permanent]
    )
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    queue = _FullQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()
    notifications_service.deliver_job(queue.deferred[0])

    assert len(logger_n.calls) == 1, "the fallback must not be delivered twice"
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_shed_send_with_nowhere_to_park_is_recorded_as_lost(
    harness: _Harness,
) -> None:
    """When both the queue and the parking lot are full the send really is
    gone — the fallback's row is then the final word, not a placeholder."""
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    queue = _FullQueueNoParking()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert sms.calls == []
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_full_queue_drops_the_email_copy_without_sending_it(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy has no ledger row and no fall-through, so overflow means
    it is simply not sent — never sent inline."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM_EMAIL", "queue@example.com")

    email = _RemoteNotifier(NotificationChannel.email)
    _registry(
        _LocalNotifier(NotificationChannel.websocket),
        email,
        _LocalNotifier(NotificationChannel.logger),
    )
    notifications_service.set_delivery_queue(_FullQueue())  # type: ignore[arg-type]
    harness.user.notification_prefs = ["websocket", "email", "logger"]

    row = harness.dispatch()

    assert email.calls == []
    assert row.channel == NotificationChannel.websocket.value
    assert row.status == NotificationStatus.delivered.value


# --- resolution: what the worker does ------------------------------------


def test_a_successful_send_resolves_the_queued_row(harness: _Harness) -> None:
    _registry(
        _RemoteNotifier(NotificationChannel.sms),
        _LocalNotifier(NotificationChannel.logger),
    )
    _inline()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value


def test_a_rejected_send_falls_through_to_the_next_preference(
    harness: _Harness,
) -> None:
    """The fall-through that used to happen inside the dispatch loop now
    happens on the worker, and rewrites the row's channel."""
    sms = _RemoteNotifier(
        NotificationChannel.sms, outcomes=[DeliveryOutcome.permanent]
    )
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    _inline()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert len(sms.calls) == 1
    assert len(logger_n.calls) == 1
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_a_transient_failure_is_retried_and_then_lands_on_sms(
    harness: _Harness,
) -> None:
    """The gap this change closes: ``SmsResult.retryable`` used to be
    logged and thrown away."""
    sms = _RemoteNotifier(
        NotificationChannel.sms,
        outcomes=[DeliveryOutcome.transient, DeliveryOutcome.delivered],
    )
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    _inline()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert len(sms.calls) == 2
    assert logger_n.calls == []
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.delivered.value


def test_a_rejected_send_is_never_retried(harness: _Harness) -> None:
    """Only ``transient`` earns another go — a permanent rejection would
    just burn quota and risk double-texting."""
    sms = _RemoteNotifier(
        NotificationChannel.sms,
        outcomes=[DeliveryOutcome.permanent, DeliveryOutcome.delivered],
    )
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    _inline()
    harness.user.notification_prefs = ["sms", "logger"]

    harness.dispatch()

    assert len(sms.calls) == 1


def test_exhausted_retries_fall_through_rather_than_giving_up(
    harness: _Harness,
) -> None:
    sms = _RemoteNotifier(
        NotificationChannel.sms, outcomes=[DeliveryOutcome.transient]
    )
    logger_n = _LocalNotifier(NotificationChannel.logger)
    _registry(sms, logger_n)
    _inline()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()

    assert len(sms.calls) == FAST.max_attempts
    assert len(logger_n.calls) == 1
    assert row.channel == NotificationChannel.logger.value
    assert row.status == NotificationStatus.delivered.value


def test_the_row_is_marked_failed_when_nothing_is_left_to_try(
    harness: _Harness,
) -> None:
    sms = _RemoteNotifier(
        NotificationChannel.sms, outcomes=[DeliveryOutcome.permanent]
    )
    _inline()
    # ``_user_prefs`` always appends the ``logger`` backstop, so the only
    # way to reach "nothing left" is a registry without one.
    notifications_service.set_registry({NotificationChannel.sms: sms})  # type: ignore[dict-item]
    harness.user.notification_prefs = ["sms"]

    row = harness.dispatch()

    # Names the channel that was actually attempted, not the unregistered
    # backstop it fell past — matching what inline dispatch used to record.
    assert row.channel == NotificationChannel.sms.value
    assert row.status == NotificationStatus.failed.value


def test_a_user_deactivated_mid_flight_is_not_texted(harness: _Harness) -> None:
    sms = _RemoteNotifier(NotificationChannel.sms)
    _registry(sms, _LocalNotifier(NotificationChannel.logger))
    queue = _capture()
    harness.user.notification_prefs = ["sms", "logger"]

    row = harness.dispatch()
    harness.user.is_active = False
    notifications_service.deliver_job(queue.jobs[0])

    assert sms.calls == []
    assert row.status == NotificationStatus.failed.value


# --- transactional hand-off (real session) -------------------------------


def _probe_job() -> DeliveryJob:
    return DeliveryJob(
        user_id=uuid.uuid4(),
        channel=NotificationChannel.sms,
        payload=NotificationPayload(
            kind=NotificationKind.you_are_next, body="you are next"
        ),
    )


def test_a_job_waits_for_the_transaction_to_commit() -> None:
    """The worker reads the ledger row from its own session, so handing
    over before the commit would race it."""
    from sqlmodel import Session

    from werefa.core.db import engine

    queue = _CaptureQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    try:
        with Session(engine) as session:
            notifications_service._hand_off(session, _probe_job())
            assert queue.jobs == []
            session.commit()
            assert len(queue.jobs) == 1
    finally:
        notifications_service.set_delivery_queue(None)


def test_a_rolled_back_transaction_texts_nobody() -> None:
    """Nobody should hear "you're next" about a ticket that never existed."""
    from sqlmodel import Session, select

    from werefa.core.db import engine

    queue = _CaptureQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    try:
        with Session(engine) as session:
            # Force a real transaction so ``after_rollback`` has something
            # to fire on.
            session.exec(select(User).limit(1)).first()
            notifications_service._hand_off(session, _probe_job())
            session.rollback()
            assert queue.jobs == []
    finally:
        notifications_service.set_delivery_queue(None)
