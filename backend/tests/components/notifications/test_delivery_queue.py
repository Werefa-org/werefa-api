"""The delivery worker's scheduling and retry mechanics (FR-07).

Exercised against a recording handler rather than the real one: this is
the transport, and what it owes the caller is "runs the job, retries the
transient ones, never wedges" — independent of notifications entirely.
The handler's own behaviour (channel fall-through, ledger updates) is
covered in ``test_deferred_dispatch.py``.

Backoff here is set to milliseconds. The *schedule* is asserted in
``test_retry_policy.py`` where it can be checked exactly; these tests
only care that a delay is honoured at all.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Generator

import pytest

from werefa.notifications.domain.retry import RetryPolicy
from werefa.notifications.infrastructure.delivery import (
    DeliveryAttempt,
    DeliveryJob,
    DeliveryQueue,
    InlineDeliveryQueue,
)
from werefa.notifications.notifier import (
    DeliveryOutcome,
    NotificationPayload,
)
from werefa.shared.enums import NotificationChannel, NotificationKind

FAST = RetryPolicy(max_attempts=3, base_seconds=0.01, max_seconds=0.05, jitter_ratio=0.0)


def _job(**overrides: object) -> DeliveryJob:
    defaults: dict[str, object] = {
        "user_id": uuid.uuid4(),
        "channel": NotificationChannel.sms,
        "payload": NotificationPayload(
            kind=NotificationKind.you_are_next, body="you are next"
        ),
    }
    defaults.update(overrides)
    return DeliveryJob(**defaults)  # type: ignore[arg-type]


class _Handler:
    """Replays a scripted list of outcomes and records what it was given."""

    def __init__(self, *outcomes: DeliveryOutcome) -> None:
        self._outcomes = list(outcomes)
        self.seen: list[DeliveryJob] = []
        self._lock = threading.Lock()

    def __call__(self, job: DeliveryJob) -> DeliveryAttempt:
        with self._lock:
            self.seen.append(job)
            index = min(len(self.seen) - 1, len(self._outcomes) - 1)
            outcome = self._outcomes[index]
        return DeliveryAttempt(outcome)


@pytest.fixture
def queue_factory() -> Generator[list[DeliveryQueue], None, None]:
    """Guarantees every queue a test starts is also stopped."""
    started: list[DeliveryQueue] = []
    yield started
    for q in started:
        q.stop(timeout=2.0)


def _queue(
    started: list[DeliveryQueue], handler: object, **kwargs: object
) -> DeliveryQueue:
    q = DeliveryQueue(handler, policy=FAST, workers=1, **kwargs)  # type: ignore[arg-type]
    started.append(q)
    return q


# --- the happy path ------------------------------------------------------


def test_submitted_job_runs_on_a_worker_not_the_caller(
    queue_factory: list[DeliveryQueue],
) -> None:
    """The whole point: the calling thread does not pay for the send."""
    ran_on: list[str] = []

    def handler(_job: DeliveryJob) -> DeliveryAttempt:
        ran_on.append(threading.current_thread().name)
        return DeliveryAttempt(DeliveryOutcome.delivered)

    q = _queue(queue_factory, handler)
    q.submit(_job())

    assert q.wait_idle(timeout=2.0)
    assert ran_on and ran_on[0] != threading.current_thread().name


def test_submit_starts_the_workers_if_the_lifespan_never_did(
    queue_factory: list[DeliveryQueue],
) -> None:
    """A management script or a test that skipped startup must not
    silently swallow every alert."""
    handler = _Handler(DeliveryOutcome.delivered)
    q = _queue(queue_factory, handler)

    assert q.running is False
    q.submit(_job())

    assert q.wait_idle(timeout=2.0)
    assert len(handler.seen) == 1


# --- retry ---------------------------------------------------------------


def test_transient_failure_is_retried_until_it_lands(
    queue_factory: list[DeliveryQueue],
) -> None:
    handler = _Handler(
        DeliveryOutcome.transient,
        DeliveryOutcome.transient,
        DeliveryOutcome.delivered,
    )
    q = _queue(queue_factory, handler)
    q.submit(_job())

    assert q.wait_idle(timeout=3.0)
    assert [j.attempt for j in handler.seen] == [0, 1, 2]


def test_permanent_failure_is_not_retried(
    queue_factory: list[DeliveryQueue],
) -> None:
    """Re-sending a message the gateway rejected burns quota and risks
    double-texting; only ``transient`` earns another go."""
    handler = _Handler(DeliveryOutcome.permanent)
    q = _queue(queue_factory, handler)
    q.submit(_job())

    assert q.wait_idle(timeout=2.0)
    assert len(handler.seen) == 1


def test_retries_stop_at_the_configured_budget(
    queue_factory: list[DeliveryQueue],
) -> None:
    handler = _Handler(DeliveryOutcome.transient)
    q = _queue(queue_factory, handler)
    q.submit(_job())

    assert q.wait_idle(timeout=3.0)
    assert len(handler.seen) == FAST.max_attempts


def test_handler_is_told_when_it_is_on_the_final_attempt(
    queue_factory: list[DeliveryQueue],
) -> None:
    """``last_attempt`` is how the retry budget stays in one place: the
    handler falls through to the next channel instead of asking for a
    retry it cannot have."""
    handler = _Handler(DeliveryOutcome.transient)
    q = _queue(queue_factory, handler)
    q.submit(_job())

    assert q.wait_idle(timeout=3.0)
    assert [j.last_attempt for j in handler.seen] == [False, False, True]


def test_a_retry_resumes_on_the_channel_the_handler_reached(
    queue_factory: list[DeliveryQueue],
) -> None:
    """The handler may have already fallen past a dead channel before
    hitting a transient one; the retry must not go back to the dead one."""
    seen: list[NotificationChannel] = []

    def handler(job: DeliveryJob) -> DeliveryAttempt:
        seen.append(job.channel)
        if len(seen) == 1:
            return DeliveryAttempt(
                DeliveryOutcome.transient,
                retry_with=DeliveryJob(
                    user_id=job.user_id,
                    channel=NotificationChannel.email,
                    payload=job.payload,
                ),
            )
        return DeliveryAttempt(DeliveryOutcome.delivered)

    q = _queue(queue_factory, handler)
    q.submit(_job(channel=NotificationChannel.sms))

    assert q.wait_idle(timeout=2.0)
    assert seen == [NotificationChannel.sms, NotificationChannel.email]


def test_a_single_attempt_budget_marks_the_first_try_final(
    queue_factory: list[DeliveryQueue],
) -> None:
    handler = _Handler(DeliveryOutcome.transient)
    q = DeliveryQueue(
        handler, policy=RetryPolicy(max_attempts=1, base_seconds=0.01), workers=1
    )
    queue_factory.append(q)
    q.submit(_job())

    assert q.wait_idle(timeout=2.0)
    assert len(handler.seen) == 1
    assert handler.seen[0].last_attempt is True


# --- staying alive under abuse -------------------------------------------


def test_the_queue_refuses_work_rather_than_growing_without_bound(
    queue_factory: list[DeliveryQueue],
) -> None:
    """A wedged gateway must not turn every queue mutation into retained
    memory. Refusing lets the caller fall through to another channel."""
    release = threading.Event()

    def handler(_job: DeliveryJob) -> DeliveryAttempt:
        release.wait(timeout=5.0)
        return DeliveryAttempt(DeliveryOutcome.delivered)

    q = _queue(queue_factory, handler, max_size=2)
    try:
        accepted = [q.submit(_job()) for _ in range(6)]
    finally:
        release.set()

    # The first is picked up immediately, so exactly ``max_size`` more fit.
    assert accepted.count(True) <= 3
    assert accepted[-1] is False
    assert q.wait_idle(timeout=3.0)


# --- overflow parking ----------------------------------------------------


def test_a_deferred_job_runs_once_the_queue_drains(
    queue_factory: list[DeliveryQueue],
) -> None:
    """The point of parking: a burst costs latency, not the channel."""
    release = threading.Event()
    handler = _Handler(DeliveryOutcome.delivered)

    def blocking(job: DeliveryJob) -> DeliveryAttempt:
        release.wait(timeout=5.0)
        return handler(job)

    # Fill it up: the worker takes one and blocks, the heap holds one more,
    # and everything after that is refused. Looping until ``submit`` says no
    # avoids racing the worker for a snapshot of ``pending``.
    q = _queue(queue_factory, blocking, max_size=1)
    while q.submit(_job()):
        pass

    parked = _job(channel=NotificationChannel.email)
    assert q.defer(parked) is True
    assert q.shed_pending == 1

    release.set()
    assert q.wait_idle(timeout=3.0)
    assert NotificationChannel.email in [j.channel for j in handler.seen]
    assert q.shed_pending == 0


def test_parking_contacts_nobody(queue_factory: list[DeliveryQueue]) -> None:
    """``defer`` runs on the request thread, so it must be pure
    bookkeeping — never a send."""
    handler = _Handler(DeliveryOutcome.delivered)
    q = DeliveryQueue(handler, policy=FAST, workers=1, max_size=1)
    queue_factory.append(q)

    assert q.defer(_job()) is True
    assert handler.seen == [], "defer must not deliver anything itself"
    assert q.shed_pending == 1


def test_the_parking_lot_is_bounded_too(
    queue_factory: list[DeliveryQueue],
) -> None:
    """Otherwise "park it for later" is just an unbounded queue with an
    extra step."""
    q = _queue(queue_factory, _Handler(DeliveryOutcome.delivered), shed_max=2)
    q.stop(timeout=1.0)  # keep workers out of it so nothing is promoted

    assert [q.defer(_job()) for _ in range(4)] == [True, True, False, False]
    assert q.shed_pending == 2


def test_a_parked_job_is_discarded_once_it_goes_stale(
    queue_factory: list[DeliveryQueue],
) -> None:
    """A queue alert delivered minutes late is worse than none — the
    customer has usually been served by then."""
    handler = _Handler(DeliveryOutcome.delivered)
    q = DeliveryQueue(
        handler, policy=FAST, workers=1, shed_ttl_seconds=0.05
    )
    queue_factory.append(q)
    q.stop(timeout=1.0)  # park without a worker racing us to promote it

    assert q.defer(_job()) is True
    time.sleep(0.1)

    q.start()
    assert q.wait_idle(timeout=2.0)
    assert handler.seen == [], "a stale alert should never be sent"
    assert q.shed_pending == 0


def test_parking_can_be_switched_off(
    queue_factory: list[DeliveryQueue],
) -> None:
    q = _queue(queue_factory, _Handler(DeliveryOutcome.delivered), shed_max=0)
    assert q.defer(_job()) is False
    assert q.shed_pending == 0


def test_shutdown_drops_parked_work_too(
    queue_factory: list[DeliveryQueue],
) -> None:
    q = _queue(queue_factory, _Handler(DeliveryOutcome.delivered))
    q.stop(timeout=1.0)
    q.defer(_job())

    q.start()
    q.stop(timeout=1.0)
    assert q.shed_pending == 0


def test_a_crashing_handler_does_not_kill_the_worker(
    queue_factory: list[DeliveryQueue],
) -> None:
    calls: list[int] = []

    def handler(_job: DeliveryJob) -> DeliveryAttempt:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic handler crash")
        return DeliveryAttempt(DeliveryOutcome.delivered)

    q = _queue(queue_factory, handler)
    q.submit(_job())
    assert q.wait_idle(timeout=2.0)

    q.submit(_job())
    assert q.wait_idle(timeout=2.0)
    assert len(calls) == 2


def test_stop_is_idempotent_and_leaves_the_queue_stopped(
    queue_factory: list[DeliveryQueue],
) -> None:
    q = _queue(queue_factory, _Handler(DeliveryOutcome.delivered))
    q.submit(_job())
    assert q.wait_idle(timeout=2.0)

    q.stop(timeout=2.0)
    q.stop(timeout=2.0)
    assert q.running is False


def test_shutdown_drops_queued_work_rather_than_hanging(
    queue_factory: list[DeliveryQueue],
) -> None:
    """Daemon workers plus a bounded join: a wedged gateway must never
    hold up a deploy. The alert is lost, which is the documented cost of
    an in-process queue."""
    release = threading.Event()

    def handler(_job: DeliveryJob) -> DeliveryAttempt:
        release.wait(timeout=5.0)
        return DeliveryAttempt(DeliveryOutcome.delivered)

    q = _queue(queue_factory, handler, max_size=10)
    for _ in range(4):
        q.submit(_job())

    q.stop(timeout=0.1)
    release.set()
    assert q.pending == 0
    assert q.running is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_size": 0},
        {"workers": 0},
        {"shed_max": -1},
        {"shed_ttl_seconds": 0.0},
    ],
)
def test_nonsense_queue_configuration_fails_loudly(
    kwargs: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        DeliveryQueue(_Handler(DeliveryOutcome.delivered), **kwargs)  # type: ignore[arg-type]


# --- the inline variant --------------------------------------------------


def test_inline_queue_runs_and_retries_on_the_calling_thread() -> None:
    """The deterministic seam tests use in place of worker threads."""
    slept: list[float] = []
    handler = _Handler(
        DeliveryOutcome.transient,
        DeliveryOutcome.delivered,
    )
    q = InlineDeliveryQueue(handler, policy=FAST, sleeper=slept.append)

    q.submit(_job())

    assert [j.attempt for j in handler.seen] == [0, 1]
    assert slept == [FAST.base_seconds]


def test_inline_queue_honours_the_same_retry_budget() -> None:
    handler = _Handler(DeliveryOutcome.transient)
    q = InlineDeliveryQueue(handler, policy=FAST, sleeper=lambda _: None)

    q.submit(_job())

    assert len(handler.seen) == FAST.max_attempts
    assert handler.seen[-1].last_attempt is True
