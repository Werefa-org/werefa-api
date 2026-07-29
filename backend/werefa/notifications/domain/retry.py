"""Backoff schedule for retrying transient notification deliveries (FR-07).

Pure arithmetic on purpose — no threads, no clock, no settings import — so
the schedule can be asserted directly in a component test instead of being
inferred from how long a worker happened to sleep.

The policy only ever runs against outcomes an adapter called *transient*
(:class:`~werefa.notifications.infrastructure.sms.base.SmsOutcome.unavailable`
and its siblings). A ``rejected`` result is never retried: re-sending a
message the gateway refused burns quota and, worse, risks double-texting
someone if the refusal was actually a partial success.

Jitter is applied *downward* only. Two calls that fail in the same second
must not line up on the same retry tick, but the cap in
``NOTIFICATION_DELIVERY_RETRY_MAX_SECONDS`` is meant to be a real ceiling —
an upward jitter would quietly exceed it.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with a ceiling.

    ``attempt`` is zero-based throughout: attempt ``0`` is the first
    delivery try, so ``max_attempts=4`` means one initial send plus three
    retries, at roughly ``base``, ``2 * base`` and ``4 * base`` seconds.
    """

    max_attempts: int = 4
    base_seconds: float = 1.0
    max_seconds: float = 60.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if not 0.0 <= self.jitter_ratio < 1.0:
            raise ValueError("jitter_ratio must be in [0, 1)")

    @classmethod
    def from_settings(cls) -> RetryPolicy:
        from werefa.core.config import settings

        return cls(
            max_attempts=settings.NOTIFICATION_DELIVERY_MAX_ATTEMPTS,
            base_seconds=settings.NOTIFICATION_DELIVERY_RETRY_BASE_SECONDS,
            max_seconds=settings.NOTIFICATION_DELIVERY_RETRY_MAX_SECONDS,
            jitter_ratio=settings.NOTIFICATION_DELIVERY_RETRY_JITTER,
        )

    def should_retry(self, attempt: int) -> bool:
        """Is another try allowed after ``attempt`` has just failed?"""
        return attempt + 1 < self.max_attempts

    def delay_for(
        self,
        attempt: int,
        *,
        rand: Callable[[], float] = random.random,
    ) -> float:
        """Seconds to wait before the try that follows ``attempt``.

        ``rand`` is injected so tests can pin the jitter instead of
        asserting on a range.
        """
        exponential: float = self.base_seconds * (2.0**attempt)
        capped: float = min(exponential, self.max_seconds)
        if self.jitter_ratio == 0.0:
            return capped
        return capped * (1.0 - self.jitter_ratio * rand())
