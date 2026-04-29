"""Pure rules for the no-show strike penalty (FR-12).

These functions take primitive types (counts, datetimes) so tests can pin time
and exercise window boundaries without a database. The application service
composes them with persistence + the active session.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class BlockEvaluation:
    """Result of evaluating whether a user is currently blocked from
    *remote* joins.

    ``is_blocked``: should the join be rejected right now.
    ``until``: when the block lifts (None when not blocked, or when the only
        cause is a stale ``joins_blocked_until`` already in the past).
    ``reason``: machine-friendly tag describing why; useful for logs/tests.
    """

    is_blocked: bool
    until: datetime | None
    reason: str


def window_start(*, now: datetime, window_days: int) -> datetime:
    """Earliest timestamp counted as "within the rolling window" right now."""
    if window_days <= 0:
        # Defensive: a zero/negative window would silently disable strikes.
        # Treating it as "no window" is the safest interpretation.
        return now
    return now - timedelta(days=window_days)


def evaluate_block(
    *,
    now: datetime,
    joins_blocked_until: datetime | None,
    strikes_in_window: int,
    limit: int,
) -> BlockEvaluation:
    """Decide whether a remote-join attempt should be rejected.

    The two independent conditions, per the spec:
      1. an explicit ``joins_blocked_until`` is still in the future, OR
      2. the user has accumulated ``>= limit`` strikes inside the window.

    The function never mutates state; the caller persists the resulting block
    timestamp via :func:`block_until_for_threshold` if condition (2) just
    fired.
    """
    if joins_blocked_until is not None and joins_blocked_until > now:
        return BlockEvaluation(
            is_blocked=True,
            until=joins_blocked_until,
            reason="explicit_block",
        )
    if limit > 0 and strikes_in_window >= limit:
        return BlockEvaluation(
            is_blocked=True,
            until=None,
            reason="strike_threshold_reached",
        )
    return BlockEvaluation(
        is_blocked=False,
        until=None,
        reason="ok",
    )


def block_until_for_threshold(*, now: datetime, block_days: int) -> datetime:
    """Compute the ``joins_blocked_until`` timestamp to persist when a strike
    accrual just crossed the limit."""
    return now + timedelta(days=max(block_days, 0))
