"""Estimated wait time computation (FR-06, FR-01).

This module is a **pure** library: no Session, no HTTP, no globals.  The
caller passes in already-resolved samples + waiting counts; the module
returns minutes (or ``None`` for "not enough data").  That keeps the
algorithm trivially unit-testable with frozen times and lets us swap the
weighting later without touching the queue service.

Algorithm (per `phase-plan.md` §8.2):

1.  Take up to ``history_limit`` most-recent **completed** samples for the
    service line, each with a serve duration (``completed_at -
    serving_started_at``) and a recency offset (now − completed_at).
2.  Compute exponential weights ``w_i = exp(-Δt_i / half_life_min)`` and
    the weighted mean serve duration.
3.  If fewer than ``min_samples`` usable samples exist, fall back to the
    provider's own ``avg_duration_minutes`` baseline.
4.  Multiply by ``waiting_count`` to get a service-line EWT.
5.  Aggregate across active service lines: ``max`` (worst case, default)
    or ``sum`` (one shared server).

All durations are in **minutes**; negative or zero serve durations are
silently dropped because they signal a clock skew or a same-second
update, both of which would distort the average.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class CompletedSample:
    """One completed-ticket data point used by the WMA."""

    serving_started_at: datetime
    completed_at: datetime


def _serve_duration_minutes(s: CompletedSample) -> float | None:
    delta = (s.completed_at - s.serving_started_at).total_seconds() / 60.0
    if delta <= 0.0:
        return None
    return delta


def _recency_minutes(*, sample: CompletedSample, now: datetime) -> float:
    raw = (now - sample.completed_at).total_seconds() / 60.0
    # Cap at zero so a sample with a slight clock-skew "future" timestamp
    # still gets the maximum weight rather than blowing up.
    return max(raw, 0.0)


def service_line_ewt_minutes(
    *,
    samples: Iterable[CompletedSample],
    waiting_count: int,
    fallback_avg_min: int,
    now: datetime,
    half_life_min: float,
    min_samples: int,
    history_limit: int,
) -> float | None:
    """Return the EWT (in minutes) for one service line, or ``None`` when
    nothing is waiting *and* there is no usable signal at all (no samples,
    no fallback).  A non-zero waiting count + fallback always yields a
    number.
    """
    if waiting_count <= 0:
        return 0.0

    usable: list[tuple[float, float]] = []  # (duration_min, recency_min)
    for s in list(samples)[:history_limit]:
        dur = _serve_duration_minutes(s)
        if dur is None:
            continue
        usable.append((dur, _recency_minutes(sample=s, now=now)))

    if len(usable) < min_samples:
        if fallback_avg_min <= 0:
            return None
        return float(fallback_avg_min) * waiting_count

    half = max(half_life_min, 1e-6)
    weights = [math.exp(-rec / half) for _, rec in usable]
    weight_sum = sum(weights)
    if weight_sum <= 0.0:  # unreachable in practice (weights > 0); defensive
        return float(fallback_avg_min) * waiting_count if fallback_avg_min > 0 else None
    weighted_sum = sum(w * d for w, (d, _) in zip(weights, usable, strict=True))
    per_ticket = weighted_sum / weight_sum
    return per_ticket * waiting_count


def provider_ewt_minutes(
    *,
    service_line_ewts: Iterable[float | None],
    aggregation: Literal["max", "sum"] = "max",
) -> float | None:
    """Aggregate per-service-line EWTs into a single provider EWT.

    ``None`` lines (no signal) are ignored; if every line is ``None``, the
    provider EWT is ``None`` too.
    """
    real = [v for v in service_line_ewts if v is not None]
    if not real:
        return None
    if aggregation == "sum":
        return sum(real)
    return max(real)


def round_minutes(value: float | None) -> int | None:
    """Helper for callers that expose an integer-minute field."""
    if value is None:
        return None
    return int(round(value))
