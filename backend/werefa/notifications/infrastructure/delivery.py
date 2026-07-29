"""Off-request delivery worker for notification channels that leave the box (FR-07).

Why this exists
---------------
``dispatch`` used to call every notifier inline, so an HTTP request did not
finish until the SMS gateway answered. Most routes are sync ``def`` and run
in the threadpool, where that only costs the one request — but
``POST /service-items/{id}/join-with-files`` is ``async def``, so a slow
gateway there held the *event loop* for up to ``SMS_TIMEOUT_SECONDS`` and
stalled every other connected client. Remote sends now go here instead.

Why a thread pool and not ``BackgroundTasks``
---------------------------------------------
``BackgroundTasks`` runs after the response, which fixes the latency half of
the problem, but a retry with backoff would occupy an ``anyio`` threadpool
worker for the whole sleep — the same pool every sync route needs. A
dedicated, separately-bounded pool keeps a flaky gateway from starving
request handling.

Why in-process and not Celery/Redis
------------------------------------
Nothing in the deployment runs a worker today (``redis`` is a dependency
only for the realtime pub/sub bridge), and a queue alert is worth seconds,
not a new moving part in ``compose.yml``. The trade is explicit: **jobs are
not durable.** A restart drops whatever is in flight, and the ledger row
stays ``queued`` rather than flipping to ``delivered`` or ``failed`` — which
is at least visible and reapable, unlike the silent loss that inline sending
had on a crash. Swapping this class for a Redis-backed queue means
reimplementing :meth:`DeliveryQueue.submit` and nothing else; the handler
and the ledger bookkeeping live in the application service.

Scheduling is a time-ordered heap rather than a plain FIFO because retries
need to become due *later* without a worker blocking on ``sleep`` in the
meantime.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

from werefa.notifications.domain.retry import RetryPolicy
from werefa.notifications.notifier import DeliveryOutcome, NotificationPayload
from werefa.shared.enums import NotificationChannel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryJob:
    """One outbound send, plus what to do when it fails.

    Carries ids rather than ORM objects: the request's ``Session`` is
    closed by the time a worker picks this up, so the handler re-loads
    everything in a session of its own.
    """

    user_id: uuid.UUID
    channel: NotificationChannel
    payload: NotificationPayload

    notification_id: uuid.UUID | None = None
    """Ledger row to resolve when delivery settles.

    ``None`` for the email *copy* of a queue-critical alert, which by
    design never owns a row — see ``EMAIL_COPY_KINDS`` in the service.
    """

    fallback_channels: tuple[NotificationChannel, ...] = ()
    """Remaining preferences, in order, if this channel fails for good.

    Channel fall-through moves here from ``dispatch``: once the send is
    asynchronous, only the worker knows whether SMS actually worked.
    """

    attempt: int = 0
    last_attempt: bool = False
    """Set by the queue. Tells the handler to stop asking for retries and
    fall through instead, so the retry budget lives in exactly one place."""

    upgrade_only: bool = False
    """Only write the ledger row if this send *succeeds*.

    Set when a job was shed under overload and parked for later: a local
    channel has already settled the row, so a failure here must not
    overwrite a delivery that really happened. A success still upgrades
    the row to this channel, which is the one the user actually ranked
    higher.
    """


@dataclass(frozen=True)
class DeliveryAttempt:
    """What the handler wants to happen next."""

    outcome: DeliveryOutcome
    retry_with: DeliveryJob | None = None
    """Job to retry instead of the original — set when the handler already
    fell through to a later channel before hitting a transient failure, so
    a retry resumes there rather than re-sending on the dead one."""


Handler = Callable[[DeliveryJob], DeliveryAttempt]


class DeliveryQueue:
    """Bounded, time-ordered job queue drained by daemon threads."""

    def __init__(
        self,
        handler: Handler,
        *,
        policy: RetryPolicy | None = None,
        max_size: int = 1000,
        workers: int = 2,
        shed_max: int = 500,
        shed_ttl_seconds: float = 120.0,
        name: str = "notification-delivery",
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if shed_max < 0:
            raise ValueError("shed_max must not be negative")
        if shed_ttl_seconds <= 0:
            raise ValueError("shed_ttl_seconds must be positive")
        self._handler = handler
        self._policy = policy or RetryPolicy()
        self._max_size = max_size
        self._worker_count = workers
        self._shed_max = shed_max
        self._shed_ttl = shed_ttl_seconds
        self._name = name

        self._cond = threading.Condition()
        self._heap: list[tuple[float, int, DeliveryJob]] = []
        # Jobs refused by a full queue, held until it drains. FIFO, and
        # since every entry gets the same TTL the deque is also ordered by
        # expiry — which is what lets the purge below stop at the head.
        self._shed: deque[tuple[float, DeliveryJob]] = deque()
        self._seq = itertools.count()
        self._threads: list[threading.Thread] = []
        self._running = False
        self._in_flight = 0

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Idempotent; safe to call from the app lifespan and from
        :meth:`submit` (a management script or a test that never opened
        the lifespan would otherwise silently drop every alert)."""
        with self._cond:
            if self._running:
                return
            self._running = True
            self._threads = [
                threading.Thread(
                    target=self._worker,
                    name=f"{self._name}-{i}",
                    daemon=True,
                )
                for i in range(self._worker_count)
            ]
            threads = list(self._threads)
        for thread in threads:
            thread.start()
        logger.info(
            "notification_delivery_started",
            extra={"workers": self._worker_count, "max_size": self._max_size},
        )

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop draining and let in-flight sends finish within ``timeout``.

        Anything still queued is dropped — daemon threads mean we never
        hold up shutdown, and a queue alert is worthless by the time the
        process comes back anyway. The count is logged so a deploy that
        routinely sheds alerts is visible.
        """
        with self._cond:
            if not self._running:
                return
            self._running = False
            dropped = len(self._heap) + len(self._shed)
            self._heap.clear()
            self._shed.clear()
            self._cond.notify_all()
            threads = list(self._threads)

        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._cond:
            self._threads = []
        if dropped:
            logger.warning(
                "notification_delivery_dropped_on_shutdown",
                extra={"dropped": dropped},
            )
        logger.info("notification_delivery_stopped")

    # --- producer side ---------------------------------------------------

    def submit(self, job: DeliveryJob) -> bool:
        """Queue ``job``. Returns ``False`` when the queue is full.

        The caller decides what a full queue means; this class refuses
        rather than blocking, because blocking here would put the request
        thread right back on the provider's latency.
        """
        self.start()
        return self._schedule(job, delay=0.0)

    def defer(self, job: DeliveryJob) -> bool:
        """Park ``job`` until the queue has room again.

        Called by the overflow path so that shedding a remote send costs
        latency rather than the channel: the caller delivers on a local
        preference right away, and this job goes out for real once the
        wedged gateway drains. Parking is pure bookkeeping — no provider
        is contacted here, so this stays safe to call on a request
        thread.

        Parked jobs expire after ``shed_ttl_seconds``. A "you're next"
        text that lands minutes late is worse than none at all, because
        by then the customer has usually been served.

        Returns ``False`` when the parking lot is also full — at which
        point the send really is lost, and the caller's local fallback is
        the final word.
        """
        if self._shed_max < 1:
            return False
        with self._cond:
            self._purge_expired_locked()
            if len(self._shed) >= self._shed_max:
                return False
            self._shed.append((time.monotonic() + self._shed_ttl, job))
            self._cond.notify()
        return True

    def _schedule(self, job: DeliveryJob, *, delay: float) -> bool:
        job = replace(job, last_attempt=not self._policy.should_retry(job.attempt))
        with self._cond:
            if len(self._heap) >= self._max_size:
                return False
            heapq.heappush(
                self._heap, (time.monotonic() + delay, next(self._seq), job)
            )
            self._cond.notify()
        return True

    def _purge_expired_locked(self) -> None:
        """Drop parked jobs that went stale. Caller holds the lock."""
        now = time.monotonic()
        while self._shed and self._shed[0][0] <= now:
            _, stale = self._shed.popleft()
            logger.warning(
                "notification_delivery_shed_expired",
                extra={
                    "channel": stale.channel.value,
                    "user_id": str(stale.user_id),
                },
            )

    def _promote_shed_locked(self) -> None:
        """Re-admit parked jobs now the queue has room. Caller holds the lock.

        Run from :meth:`_take`, so re-admission happens exactly when a
        worker is ready for more work — no separate promoter thread, and
        no way to overshoot ``max_size``.
        """
        self._purge_expired_locked()
        now = time.monotonic()
        while self._shed and len(self._heap) < self._max_size:
            _, job = self._shed.popleft()
            heapq.heappush(self._heap, (now, next(self._seq), job))
            logger.info(
                "notification_delivery_shed_promoted",
                extra={
                    "channel": job.channel.value,
                    "user_id": str(job.user_id),
                },
            )

    # --- introspection (mostly for tests and health checks) --------------

    @property
    def pending(self) -> int:
        with self._cond:
            return len(self._heap)

    @property
    def shed_pending(self) -> int:
        """Jobs parked waiting for capacity — a useful overload signal."""
        with self._cond:
            return len(self._shed)

    @property
    def running(self) -> bool:
        with self._cond:
            return self._running

    def wait_idle(self, *, timeout: float = 5.0) -> bool:
        """Block until nothing is queued, parked or in flight.

        Parked jobs count: they are still owed a send, and a test that
        stopped waiting before they were promoted would be asserting on a
        half-finished queue.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._heap or self._in_flight or self._shed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)
        return True

    # --- consumer side ---------------------------------------------------

    def _worker(self) -> None:
        while True:
            job = self._take()
            if job is None:
                return
            try:
                self._run(job)
            finally:
                with self._cond:
                    self._in_flight -= 1
                    self._cond.notify_all()

    def _take(self) -> DeliveryJob | None:
        with self._cond:
            while True:
                if not self._running:
                    return None
                # Capacity has just freed up if this worker finished a job,
                # so this is the moment to re-admit anything shed earlier.
                self._promote_shed_locked()
                if not self._heap:
                    self._cond.wait()
                    continue
                ready_at, _, job = self._heap[0]
                now = time.monotonic()
                if ready_at > now:
                    # Sleep on the condition, not on the clock, so a job
                    # submitted meanwhile still wakes us immediately.
                    self._cond.wait(timeout=ready_at - now)
                    continue
                heapq.heappop(self._heap)
                self._in_flight += 1
                return job

    def _run(self, job: DeliveryJob) -> None:
        try:
            attempt = self._handler(job)
        except Exception:  # noqa: BLE001 — one bad job must not kill a worker
            logger.exception(
                "notification_delivery_handler_crashed",
                extra={
                    "channel": job.channel.value,
                    "user_id": str(job.user_id),
                },
            )
            return

        if attempt.outcome is not DeliveryOutcome.transient:
            return

        if job.last_attempt or not self._policy.should_retry(job.attempt):
            # The handler is told ``last_attempt`` precisely so it falls
            # through instead of asking for a retry it cannot have.
            logger.error(
                "notification_delivery_transient_after_final_attempt",
                extra={
                    "channel": job.channel.value,
                    "attempt": job.attempt,
                    "user_id": str(job.user_id),
                },
            )
            return

        retry = replace(attempt.retry_with or job, attempt=job.attempt + 1)
        delay = self._policy.delay_for(job.attempt)
        if not self._schedule(retry, delay=delay):
            logger.error(
                "notification_delivery_retry_dropped_queue_full",
                extra={
                    "channel": retry.channel.value,
                    "user_id": str(retry.user_id),
                },
            )
            return
        logger.info(
            "notification_delivery_retry_scheduled",
            extra={
                "channel": retry.channel.value,
                "attempt": retry.attempt,
                "delay_seconds": round(delay, 3),
            },
        )


class InlineDeliveryQueue:
    """Same surface as :class:`DeliveryQueue`, run on the calling thread.

    Two uses. Tests swap it in to make an otherwise-asynchronous
    assertion deterministic without sleeping on real worker threads. And
    it is the shape the rest of the code would need if a deployment ever
    wanted retries without the extra threads.

    ``sleeper`` is injected so a test can assert the backoff schedule
    (see ``delays``) instead of actually waiting it out.
    """

    def __init__(
        self,
        handler: Handler,
        *,
        policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._handler = handler
        self._policy = policy or RetryPolicy()
        self._sleeper = sleeper
        self.delays: list[float] = []

    def start(self) -> None:
        return None

    def stop(self, *, timeout: float = 5.0) -> None:
        return None

    @property
    def pending(self) -> int:
        return 0

    @property
    def shed_pending(self) -> int:
        return 0

    @property
    def running(self) -> bool:
        return True

    def wait_idle(self, *, timeout: float = 5.0) -> bool:
        return True

    def defer(self, job: DeliveryJob) -> bool:
        """Never reached in practice — :meth:`submit` here always accepts,
        so there is nothing to shed. Present for interface parity."""
        return self.submit(job)

    def submit(self, job: DeliveryJob) -> bool:
        while True:
            job = replace(
                job, last_attempt=not self._policy.should_retry(job.attempt)
            )
            attempt = self._handler(job)
            if attempt.outcome is not DeliveryOutcome.transient:
                return True
            if job.last_attempt:
                return True
            delay = self._policy.delay_for(job.attempt)
            self.delays.append(delay)
            self._sleeper(delay)
            job = replace(attempt.retry_with or job, attempt=job.attempt + 1)
