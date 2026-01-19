"""Pure-rule tests for the no-show penalty (FR-12).

These tests use frozen ``datetime`` values so window-boundary semantics are
fully deterministic and don't depend on real wall-clock time.
"""

from datetime import datetime, timedelta, timezone

from werefa.strikes.domain.strike_rules import (
    block_until_for_threshold,
    evaluate_block,
    window_start,
)

NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)


def test_window_start_subtracts_configured_days() -> None:
    assert window_start(now=NOW, window_days=30) == NOW - timedelta(days=30)


def test_window_start_with_zero_or_negative_days_disables_lookback() -> None:
    assert window_start(now=NOW, window_days=0) == NOW
    assert window_start(now=NOW, window_days=-1) == NOW


def test_evaluate_block_below_limit_is_not_blocked() -> None:
    decision = evaluate_block(
        now=NOW,
        joins_blocked_until=None,
        strikes_in_window=2,
        limit=3,
    )
    assert decision.is_blocked is False
    assert decision.until is None
    assert decision.reason == "ok"


def test_evaluate_block_at_limit_is_blocked_via_threshold() -> None:
    decision = evaluate_block(
        now=NOW,
        joins_blocked_until=None,
        strikes_in_window=3,
        limit=3,
    )
    assert decision.is_blocked is True
    assert decision.until is None  # caller materialises the timestamp
    assert decision.reason == "strike_threshold_reached"


def test_evaluate_block_explicit_block_takes_precedence() -> None:
    until = NOW + timedelta(hours=1)
    decision = evaluate_block(
        now=NOW,
        joins_blocked_until=until,
        strikes_in_window=0,
        limit=3,
    )
    assert decision.is_blocked is True
    assert decision.until == until
    assert decision.reason == "explicit_block"


def test_evaluate_block_past_explicit_block_is_ignored() -> None:
    decision = evaluate_block(
        now=NOW,
        joins_blocked_until=NOW - timedelta(seconds=1),
        strikes_in_window=0,
        limit=3,
    )
    assert decision.is_blocked is False
    assert decision.reason == "ok"


def test_evaluate_block_zero_limit_disables_threshold_check() -> None:
    # Defensive: a misconfigured 0 limit should not block everyone forever.
    decision = evaluate_block(
        now=NOW,
        joins_blocked_until=None,
        strikes_in_window=99,
        limit=0,
    )
    assert decision.is_blocked is False


def test_block_until_for_threshold_adds_days() -> None:
    assert block_until_for_threshold(now=NOW, block_days=7) == NOW + timedelta(
        days=7
    )


def test_block_until_for_threshold_clamps_negative_days_to_zero() -> None:
    assert block_until_for_threshold(now=NOW, block_days=-3) == NOW
