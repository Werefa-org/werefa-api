"""Pure-math tests for the EWT WMA (FR-06, FR-01).

These tests are intentionally DB-free; everything the algorithm needs is
fed in as primitives so we can pin time and check the formula.
"""

import math
from datetime import datetime, timedelta, timezone

from werefa.queue.application.ewt import (
    CompletedSample,
    provider_ewt_minutes,
    round_minutes,
    service_line_ewt_minutes,
)

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def _sample(*, started_min_ago: float, duration_min: float) -> CompletedSample:
    completed = NOW - timedelta(minutes=started_min_ago)
    started = completed - timedelta(minutes=duration_min)
    return CompletedSample(serving_started_at=started, completed_at=completed)


def test_zero_waiting_returns_zero() -> None:
    assert (
        service_line_ewt_minutes(
            samples=[],
            waiting_count=0,
            fallback_avg_min=15,
            now=NOW,
            half_life_min=30,
            min_samples=3,
            history_limit=50,
        )
        == 0.0
    )


def test_cold_start_uses_fallback() -> None:
    ewt = service_line_ewt_minutes(
        samples=[],
        waiting_count=4,
        fallback_avg_min=15,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=50,
    )
    assert ewt == 60.0


def test_below_min_samples_uses_fallback() -> None:
    samples = [_sample(started_min_ago=5, duration_min=20)]
    ewt = service_line_ewt_minutes(
        samples=samples,
        waiting_count=2,
        fallback_avg_min=15,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=50,
    )
    assert ewt == 30.0


def test_wma_matches_manual_formula() -> None:
    samples = [
        _sample(started_min_ago=8, duration_min=2),
        _sample(started_min_ago=6, duration_min=4),
        _sample(started_min_ago=4, duration_min=6),
    ]
    ewt = service_line_ewt_minutes(
        samples=samples,
        waiting_count=3,
        fallback_avg_min=10,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=50,
    )
    weights = [math.exp(-r / 30) for r in (8, 6, 4)]
    expected = sum(w * d for w, d in zip(weights, (2, 4, 6))) / sum(weights) * 3
    assert ewt is not None
    assert abs(ewt - expected) < 1e-9


def test_wma_zero_or_negative_durations_dropped() -> None:
    bad = CompletedSample(serving_started_at=NOW, completed_at=NOW)
    same_second = CompletedSample(
        serving_started_at=NOW - timedelta(seconds=1),
        completed_at=NOW - timedelta(seconds=1),
    )
    ok = [
        _sample(started_min_ago=2, duration_min=5),
        _sample(started_min_ago=4, duration_min=7),
        _sample(started_min_ago=6, duration_min=9),
    ]
    ewt = service_line_ewt_minutes(
        samples=[bad, same_second, *ok],
        waiting_count=1,
        fallback_avg_min=10,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=50,
    )
    assert ewt is not None and ewt > 0


def test_history_limit_truncates_oldest_first() -> None:
    samples = [
        _sample(started_min_ago=i + 1, duration_min=10) for i in range(100)
    ]
    # With history_limit=5 we should still produce a positive WMA close to
    # the constant 10-minute serve duration × waiting count.
    ewt = service_line_ewt_minutes(
        samples=samples,
        waiting_count=2,
        fallback_avg_min=999,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=5,
    )
    assert ewt is not None
    assert 19.0 < ewt < 21.0


def test_recency_in_future_does_not_blow_up() -> None:
    """If a sample's completed_at is slightly in the future (clock skew), it
    should be clamped to "now" rather than producing a giant weight."""
    skewed = CompletedSample(
        serving_started_at=NOW - timedelta(minutes=5),
        completed_at=NOW + timedelta(seconds=2),
    )
    normal = [
        _sample(started_min_ago=4, duration_min=4),
        _sample(started_min_ago=6, duration_min=4),
    ]
    ewt = service_line_ewt_minutes(
        samples=[skewed, *normal],
        waiting_count=1,
        fallback_avg_min=99,
        now=NOW,
        half_life_min=30,
        min_samples=3,
        history_limit=50,
    )
    assert ewt is not None
    assert 4.0 < ewt < 6.0


def test_provider_ewt_aggregation_max_sum_and_none() -> None:
    assert (
        provider_ewt_minutes(
            service_line_ewts=[5.0, 10.0, None], aggregation="max"
        )
        == 10.0
    )
    assert (
        provider_ewt_minutes(
            service_line_ewts=[5.0, 10.0, None], aggregation="sum"
        )
        == 15.0
    )
    assert provider_ewt_minutes(service_line_ewts=[None, None]) is None


def test_round_minutes_handles_none_and_floats() -> None:
    assert round_minutes(None) is None
    assert round_minutes(12.4) == 12
    assert round_minutes(12.5) in (12, 13)  # banker's rounding tolerance
    assert round_minutes(12.6) == 13
