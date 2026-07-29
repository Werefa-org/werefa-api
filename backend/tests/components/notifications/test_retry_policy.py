"""Backoff schedule for retried deliveries (FR-07).

Pure arithmetic, so the schedule is asserted directly rather than
inferred from how long a worker slept. ``rand`` is pinned everywhere a
delay is checked — an unpinned jitter would make these assertions a
range check, which is exactly the vagueness the policy exists to avoid.
"""

from __future__ import annotations

import pytest

from werefa.notifications.domain.retry import RetryPolicy


def _policy(**overrides: object) -> RetryPolicy:
    defaults: dict[str, object] = {
        "max_attempts": 4,
        "base_seconds": 1.0,
        "max_seconds": 60.0,
        "jitter_ratio": 0.0,
    }
    defaults.update(overrides)
    return RetryPolicy(**defaults)  # type: ignore[arg-type]


def test_delay_doubles_with_each_attempt() -> None:
    policy = _policy(base_seconds=2.0)
    assert [policy.delay_for(i) for i in range(4)] == [2.0, 4.0, 8.0, 16.0]


def test_delay_is_capped() -> None:
    """A gateway that is down for hours must not push a retry hours out —
    a queue alert is worthless by then."""
    policy = _policy(base_seconds=1.0, max_seconds=5.0)
    assert policy.delay_for(10) == 5.0


def test_jitter_only_ever_shortens_the_delay() -> None:
    """Upward jitter would quietly breach ``max_seconds``."""
    policy = _policy(base_seconds=10.0, max_seconds=10.0, jitter_ratio=0.25)

    assert policy.delay_for(0, rand=lambda: 0.0) == 10.0
    assert policy.delay_for(0, rand=lambda: 1.0) == pytest.approx(7.5)
    assert policy.delay_for(0, rand=lambda: 0.5) == pytest.approx(8.75)


def test_jitter_spreads_two_failures_that_landed_together() -> None:
    policy = _policy(base_seconds=8.0, jitter_ratio=0.5)
    first = policy.delay_for(0, rand=lambda: 0.1)
    second = policy.delay_for(0, rand=lambda: 0.9)
    assert first != second
    assert 4.0 <= second <= first <= 8.0


def test_should_retry_counts_the_initial_send_as_an_attempt() -> None:
    """``max_attempts=3`` means one send plus two retries, not three retries."""
    policy = _policy(max_attempts=3)
    assert policy.should_retry(0) is True
    assert policy.should_retry(1) is True
    assert policy.should_retry(2) is False


def test_a_single_attempt_policy_never_retries() -> None:
    assert _policy(max_attempts=1).should_retry(0) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_attempts": 0},
        {"base_seconds": 0.0},
        {"base_seconds": -1.0},
        {"base_seconds": 10.0, "max_seconds": 5.0},
        {"jitter_ratio": 1.0},
        {"jitter_ratio": -0.1},
    ],
)
def test_nonsense_configuration_fails_loudly(overrides: dict[str, object]) -> None:
    """Caught at construction, which is app startup — a typo'd env var
    should not surface as a notification that silently never retries."""
    with pytest.raises(ValueError):
        _policy(**overrides)


def test_from_settings_reads_the_configured_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from werefa.core.config import settings

    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_MAX_ATTEMPTS", 7)
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_RETRY_BASE_SECONDS", 3.0)
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_RETRY_MAX_SECONDS", 99.0)
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_RETRY_JITTER", 0.0)

    policy = RetryPolicy.from_settings()
    assert policy.max_attempts == 7
    assert policy.delay_for(1) == 6.0
