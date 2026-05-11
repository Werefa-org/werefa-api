"""Provider-facing analytics from queue tickets + demand events (UC-07)."""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import or_
from sqlmodel import Session, col, select

from werefa.shared.enums import DemandEventType, TicketStatus
from werefa.shared.models import (
    AnalyticsComparison,
    AnalyticsHighlight,
    AnalyticsPeakSlot,
    AnalyticsStreaks,
    DemandEvent,
    ProviderAnalyticsPublic,
    ProviderAnalyticsServiceLine,
    ProviderAnalyticsSummary,
    QueueEntry,
    ServiceItem,
    TimeBucket,
    utcnow,
)

DataQuality = Literal["rich", "sparse", "empty"]

WEEKDAY_FULL = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

JOIN_EVENT_TYPES = frozenset(
    {
        DemandEventType.join_remote.value,
        DemandEventType.join_walk_in.value,
        DemandEventType.join_qr.value,
        DemandEventType.join_walk_in_batch.value,
    }
)


def _range_bounds(*, days: int) -> tuple[datetime, datetime]:
    end = utcnow()
    start = end - timedelta(days=max(1, min(days, 90)))
    return start, end


def _business_hour_weight(hour: int) -> float:
    if hour < 6 or hour > 21:
        return 0.12
    return 0.12 + 0.88 * math.exp(-((hour - 13) ** 2) / 20.0)


def _blend_hourly(real: list[int]) -> tuple[list[int], bool]:
    total = sum(real)
    if total >= 15:
        return real, False
    if total == 0:
        return real, False
    peak = max(real) or 1
    out: list[int] = []
    for h, v in enumerate(real):
        prior = _business_hour_weight(h) * peak
        out.append(max(v, round(v * 0.88 + prior * 0.1)))
    return out, True


def _blend_daily(real: list[int]) -> tuple[list[int], bool]:
    total = sum(real)
    if total >= 10 or total == 0:
        return real, False
    avg = total / len(real) if real else 0
    out = [max(v, round(avg * 0.85 + v * 0.15)) if v == 0 else v for v in real]
    return out, True


def _avg_minutes(deltas: list[float]) -> int | None:
    if not deltas:
        return None
    return int(round(sum(deltas) / len(deltas)))


def _min_max_minutes(deltas: list[float]) -> tuple[int | None, int | None]:
    if not deltas:
        return None, None
    return int(round(min(deltas))), int(round(max(deltas)))


def _format_hour_12(h: int) -> str:
    if h == 0:
        return "12:00 AM"
    if h < 12:
        return f"{h}:00 AM"
    if h == 12:
        return "12:00 PM"
    return f"{h - 12}:00 PM"


def _pct_diff(part: float, whole: float) -> str | None:
    if whole <= 0:
        return None
    diff = round(100.0 * (part - whole) / whole)
    if diff == 0:
        return "about the same as average"
    direction = "busier" if diff > 0 else "quieter"
    return f"{abs(diff)}% {direction} than your average"


def _slot_peak(
    values: list[int],
    *,
    kind: str,
    metric_label: str,
    label_fn,
    direction: str,
    explanation_fn,
) -> AnalyticsPeakSlot | None:
    if not values or max(values) <= 0:
        return None
    if direction == "best":
        idx = max(range(len(values)), key=lambda i: values[i])
    else:
        active = [i for i, v in enumerate(values) if v > 0]
        if not active:
            return None
        idx = min(active, key=lambda i: values[i])
    return AnalyticsPeakSlot(
        kind=kind,
        direction=direction,
        label=label_fn(idx),
        metric_label=metric_label,
        metric_value=str(values[idx]),
        explanation=explanation_fn(idx, values[idx]),
    )


def _compute_streaks(
    daily_joins_map: dict[str, int],
    *,
    period_start: date,
    period_end: date,
    queue_clears: int,
) -> AnalyticsStreaks:
    active_days = sum(1 for v in daily_joins_map.values() if v > 0)
    total_days = (period_end - period_start).days + 1
    quiet_days = max(0, total_days - active_days)

    sorted_dates = sorted(daily_joins_map.keys())
    longest_busy = 0
    current_busy = 0
    run = 0
    for d in sorted_dates:
        if daily_joins_map[d] > 0:
            run += 1
            longest_busy = max(longest_busy, run)
        else:
            run = 0
    # Current streak ending at last day with activity
    if sorted_dates:
        for d in reversed(sorted_dates):
            if daily_joins_map[d] > 0:
                current_busy += 1
            else:
                break

    weekday_totals = [0] * 7
    for d_str, count in daily_joins_map.items():
        if count > 0:
            d = date.fromisoformat(d_str)
            weekday_totals[d.weekday()] += count

    busiest_name = None
    quietest_name = None
    if sum(weekday_totals) > 0:
        busiest_idx = max(range(7), key=lambda i: weekday_totals[i])
        quiet_candidates = [i for i, v in enumerate(weekday_totals) if v > 0]
        if quiet_candidates:
            quietest_idx = min(quiet_candidates, key=lambda i: weekday_totals[i])
            busiest_name = WEEKDAY_FULL[busiest_idx]
            quietest_name = WEEKDAY_FULL[quietest_idx]

    return AnalyticsStreaks(
        active_days=active_days,
        quiet_days=quiet_days,
        current_busy_streak_days=current_busy,
        longest_busy_streak_days=longest_busy,
        times_queue_cleared=queue_clears,
        busiest_day_name=busiest_name,
        quietest_day_name=quietest_name,
    )


def _build_highlights(
    *,
    summary: ProviderAnalyticsSummary,
    peak_hour: int | None,
    quiet_hour: int | None,
    peak_leave_hour: int | None,
    best_weekday_idx: int | None,
    worst_weekday_idx: int | None,
    weekday_joins: list[int],
    fastest_day_label: str | None,
    slowest_day_label: str | None,
    data_quality: DataQuality,
) -> list[AnalyticsHighlight]:
    cards: list[AnalyticsHighlight] = []
    if data_quality == "empty":
        cards.append(
            AnalyticsHighlight(
                id="empty",
                title="Getting started",
                value="No data yet",
                detail="Serve customers for a few days to unlock patterns, streaks, and comparisons.",
                tone="neutral",
            )
        )
        return cards

    if summary.customers_helped > 0:
        cards.append(
            AnalyticsHighlight(
                id="helped",
                title="Customers served",
                value=str(summary.customers_helped),
                detail=f"Completed visits in the last period (avg wait {summary.avg_wait_minutes or '—'} min).",
                tone="good",
            )
        )

    if peak_hour is not None:
        cards.append(
            AnalyticsHighlight(
                id="peak_join",
                title="Most people join",
                value=_format_hour_12(peak_hour),
                detail="Your busiest hour for new queue joins — plan staff accordingly.",
                tone="neutral",
            )
        )

    if quiet_hour is not None and quiet_hour != peak_hour:
        cards.append(
            AnalyticsHighlight(
                id="quiet_join",
                title="Quietest join hour",
                value=_format_hour_12(quiet_hour),
                detail="Fewest people join at this time — good for breaks or admin.",
                tone="good",
            )
        )

    if summary.lost_demand_total > 0:
        cards.append(
            AnalyticsHighlight(
                id="lost_demand",
                title="Lost demand",
                value=str(summary.lost_demand_total),
                detail=(
                    "Joined the queue but did not finish "
                    f"({summary.customer_left_voluntarily} left on their own, "
                    f"{summary.cancellations} cancelled, {summary.no_shows} no-show)."
                ),
                tone="caution",
            )
        )

    if peak_leave_hour is not None:
        cards.append(
            AnalyticsHighlight(
                id="peak_leave",
                title="Lost demand peaks at",
                value=_format_hour_12(peak_leave_hour),
                detail="Most customers leave the queue around this hour.",
                tone="caution",
            )
        )

    if best_weekday_idx is not None:
        wd_avg = (
            sum(weekday_joins) / max(1, sum(1 for v in weekday_joins if v > 0))
            if sum(weekday_joins) > 0
            else 0.0
        )
        cards.append(
            AnalyticsHighlight(
                id="best_day",
                title="Best day of the week",
                value=WEEKDAY_FULL[best_weekday_idx],
                detail=_pct_diff(float(weekday_joins[best_weekday_idx]), wd_avg)
                or "Typically your strongest weekday for joins.",
                tone="good",
            )
        )

    if worst_weekday_idx is not None and worst_weekday_idx != best_weekday_idx:
        cards.append(
            AnalyticsHighlight(
                id="worst_day",
                title="Slowest day of the week",
                value=WEEKDAY_FULL[worst_weekday_idx],
                detail="Fewer joins than other days — consider promotions or adjusted hours.",
                tone="caution",
            )
        )

    if summary.max_wait_minutes is not None:
        cards.append(
            AnalyticsHighlight(
                id="wait_range",
                title="Wait time range",
                value=f"{summary.min_wait_minutes or 0}–{summary.max_wait_minutes} min",
                detail=f"Average wait is {summary.avg_wait_minutes} min across completed visits.",
                tone="neutral",
            )
        )

    if fastest_day_label:
        cards.append(
            AnalyticsHighlight(
                id="fastest_day",
                title="Fastest day",
                value=fastest_day_label,
                detail="Shortest average wait among days with completed visits.",
                tone="good",
            )
        )

    if slowest_day_label and slowest_day_label != fastest_day_label:
        cards.append(
            AnalyticsHighlight(
                id="slowest_day",
                title="Slowest day",
                value=slowest_day_label,
                detail="Longest average wait — check staffing or queue length that day.",
                tone="bad",
            )
        )

    if summary.leave_rate_pct is not None and summary.leave_rate_pct > 0:
        cards.append(
            AnalyticsHighlight(
                id="leave_rate",
                title="Leave rate",
                value=f"{summary.leave_rate_pct:.0f}%",
                detail="Share of joins that ended without a completed visit (cancel, no-show, abandon).",
                tone="caution" if summary.leave_rate_pct > 15 else "neutral",
            )
        )

    return cards[:10]


def _build_comparisons(
    *,
    weekday_joins: list[int],
    daily_joins_first_half: int,
    daily_joins_second_half: int,
    period_label: str,
) -> list[AnalyticsComparison]:
    rows: list[AnalyticsComparison] = []
    weekend = weekday_joins[5] + weekday_joins[6]
    weekday = sum(weekday_joins[:5])
    if weekend + weekday > 0:
        if weekend >= weekday:
            verdict = "Weekends draw more joins than weekdays in this period."
        else:
            verdict = "Weekdays draw more joins than weekends in this period."
        rows.append(
            AnalyticsComparison(
                label="Weekend vs weekday",
                period_a_label="Mon–Fri",
                period_a_value=str(weekday),
                period_b_label="Sat–Sun",
                period_b_value=str(weekend),
                verdict=verdict,
            )
        )

    if daily_joins_first_half + daily_joins_second_half > 0:
        if daily_joins_second_half > daily_joins_first_half:
            verdict = f"Activity picked up in the second half of the {period_label}."
        elif daily_joins_second_half < daily_joins_first_half:
            verdict = f"Activity slowed in the second half of the {period_label}."
        else:
            verdict = "Join volume was steady across both halves of the period."
        rows.append(
            AnalyticsComparison(
                label="First vs second half",
                period_a_label="Earlier",
                period_a_value=str(daily_joins_first_half),
                period_b_label="Recent",
                period_b_value=str(daily_joins_second_half),
                verdict=verdict,
            )
        )
    return rows


def _narrative(
    *,
    summary: ProviderAnalyticsSummary,
    streaks: AnalyticsStreaks,
    peak_hour: int | None,
    data_quality: DataQuality,
    range_days: int,
) -> str:
    if data_quality == "empty":
        return (
            f"In the last {range_days} days there was not enough queue activity to analyze. "
            "Keep your line open and customers will start to see patterns here."
        )
    parts: list[str] = []
    parts.append(
        f"Over the last {range_days} days you had {summary.joins} queue join(s) "
        f"and served {summary.customers_helped} customer(s) successfully."
    )
    if streaks.active_days > 0:
        parts.append(
            f"You had customers on {streaks.active_days} day(s) "
            f"({streaks.quiet_days} quiet day(s) with no joins)."
        )
    if peak_hour is not None:
        parts.append(f"Most people joined around {_format_hour_12(peak_hour)}.")
    if summary.avg_wait_minutes is not None:
        parts.append(
            f"Typical wait before service was about {summary.avg_wait_minutes} minutes "
            f"(shortest {summary.min_wait_minutes or '—'}, longest {summary.max_wait_minutes or '—'})."
        )
    if streaks.busiest_day_name:
        parts.append(f"{streaks.busiest_day_name} was usually your busiest weekday.")
    if summary.lost_demand_total > 0:
        parts.append(
            f"{summary.lost_demand_total} customer(s) joined but left without being served "
            f"({summary.leave_rate_pct or 0}% leave rate)."
        )
    if streaks.times_queue_cleared > 0:
        parts.append(
            f"The queue was cleared at end-of-day {streaks.times_queue_cleared} time(s)."
        )
    if data_quality == "sparse":
        parts.append("More history will make these patterns sharper.")
    return " ".join(parts)


def _insights(
    *,
    summary: ProviderAnalyticsSummary,
    peak_hour: int | None,
    quiet_hour: int | None,
    peak_leave_hour: int | None,
    data_quality: DataQuality,
    streaks: AnalyticsStreaks,
) -> list[str]:
    tips: list[str] = []
    if data_quality == "empty":
        tips.append(
            "Not enough activity yet. Run your queue for a few days to unlock "
            "best/worst times, wait stats, and streaks."
        )
        return tips

    if peak_hour is not None:
        tips.append(
            f"Most joins happen around {_format_hour_12(peak_hour)} — "
            "have enough staff ready then."
        )
    if quiet_hour is not None and quiet_hour != peak_hour:
        tips.append(
            f"Fewest joins around {_format_hour_12(quiet_hour)} — "
            "a good window for breaks or closing admin."
        )
    if peak_leave_hour is not None:
        tips.append(
            f"Most people leave without finishing around {_format_hour_12(peak_leave_hour)} — "
            "check wait times or messaging then."
        )
    if streaks.busiest_day_name and streaks.quietest_day_name:
        if streaks.busiest_day_name != streaks.quietest_day_name:
            tips.append(
                f"{streaks.busiest_day_name} is your strongest day; "
                f"{streaks.quietest_day_name} is usually the slowest."
            )
    if streaks.longest_busy_streak_days >= 2:
        tips.append(
            f"Your longest run of busy days in a row was {streaks.longest_busy_streak_days} day(s)."
        )
    if summary.page_views > 0 and summary.joins > 0:
        rate = 100.0 * summary.joins / max(summary.page_views, 1)
        tips.append(f"About {rate:.0f}% of page views turned into a queue join.")
    if summary.abandonments > 0:
        tips.append(
            f"{summary.abandonments} customer(s) left the queue before being served."
        )
    if summary.lost_demand_total > 0:
        tips.append(
            f"{summary.lost_demand_total} customer(s) joined the queue but left "
            "without being served — review wait times at peak leave hours."
        )
    if summary.browse_without_join > 0:
        tips.append(
            f"{summary.browse_without_join} people viewed your page without joining — "
            "check pause status, wait estimate, or join radius."
        )
    if data_quality == "sparse":
        tips.append("Limited history — some empty hours use a light estimate on charts only.")
    return tips[:8]


def build_provider_analytics(
    session: Session,
    *,
    provider_id: uuid.UUID,
    service_item_id: uuid.UUID | None = None,
    days: int = 30,
) -> ProviderAnalyticsPublic:
    start, end = _range_bounds(days=days)

    svc_stmt = select(ServiceItem).where(ServiceItem.provider_id == provider_id)
    if service_item_id is not None:
        svc_stmt = svc_stmt.where(ServiceItem.id == service_item_id)
    services = list(session.exec(svc_stmt).all())
    service_ids = [s.id for s in services]
    service_names = {s.id: s.name for s in services}

    tickets: list[QueueEntry] = []
    if service_ids:
        tickets = list(
            session.exec(
                select(QueueEntry)
                .where(col(QueueEntry.service_item_id).in_(service_ids))
                .where(col(QueueEntry.joined_at) >= start)
                .where(col(QueueEntry.joined_at) <= end)
            ).all()
        )

    events: list[DemandEvent] = []
    if service_ids:
        ev_stmt = (
            select(DemandEvent)
            .where(DemandEvent.provider_id == provider_id)
            .where(col(DemandEvent.created_at) >= start)
            .where(col(DemandEvent.created_at) <= end)
        )
        if service_item_id is not None:
            ev_stmt = ev_stmt.where(
                or_(
                    DemandEvent.service_item_id == service_item_id,
                    col(DemandEvent.service_item_id).is_(None),
                )
            )
        else:
            ev_stmt = ev_stmt.where(
                or_(
                    col(DemandEvent.service_item_id).in_(service_ids),
                    col(DemandEvent.service_item_id).is_(None),
                )
            )
        events = list(session.exec(ev_stmt).all())

    hourly_joins = [0] * 24
    hourly_leaves = [0] * 24
    hourly_completions = [0] * 24
    wait_mins: list[float] = []
    serve_mins: list[float] = []
    daily_wait: dict[str, list[float]] = defaultdict(list)
    outcomes: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    by_service: dict[uuid.UUID, dict[str, int]] = defaultdict(
        lambda: {"joins": 0, "completed": 0, "cancelled": 0, "no_show": 0}
    )
    daily_joins_map: dict[str, int] = defaultdict(int)
    daily_leaves_map: dict[str, int] = defaultdict(int)
    weekday_joins = [0] * 7
    weekday_leaves = [0] * 7

    for t in tickets:
        if t.joined_at:
            hourly_joins[t.joined_at.hour] += 1
            key = t.joined_at.date().isoformat()
            daily_joins_map[key] += 1
            weekday_joins[t.joined_at.weekday()] += 1
        outcomes[t.status] = outcomes.get(t.status, 0) + 1
        by_source[t.source] = by_source.get(t.source, 0) + 1
        sid = t.service_item_id
        by_service[sid]["joins"] += 1

        leave_ts: datetime | None = None
        if t.status == TicketStatus.completed.value:
            by_service[sid]["completed"] += 1
            if t.joined_at and t.completed_at:
                w = (t.completed_at - t.joined_at).total_seconds() / 60
                wait_mins.append(w)
                daily_wait[t.joined_at.date().isoformat()].append(w)
            if t.serving_started_at and t.completed_at:
                serve_mins.append(
                    (t.completed_at - t.serving_started_at).total_seconds() / 60
                )
            if t.completed_at:
                hourly_completions[t.completed_at.hour] += 1
        elif t.status in (
            TicketStatus.cancelled.value,
            TicketStatus.no_show.value,
        ):
            if t.status == TicketStatus.cancelled.value:
                by_service[sid]["cancelled"] += 1
            else:
                by_service[sid]["no_show"] += 1
            leave_ts = t.completed_at or t.joined_at

        if leave_ts:
            hourly_leaves[leave_ts.hour] += 1
            dkey = leave_ts.date().isoformat()
            daily_leaves_map[dkey] += 1
            weekday_leaves[leave_ts.weekday()] += 1

    views = sum(1 for e in events if e.event_type == DemandEventType.service_view.value)
    joins_ev = sum(1 for e in events if e.event_type in JOIN_EVENT_TYPES)
    abandons = sum(
        1 for e in events if e.event_type == DemandEventType.queue_abandon.value
    )
    cleared = sum(
        1 for e in events if e.event_type == DemandEventType.queue_cleared.value
    )

    ticket_joins = len(tickets)
    joins_total = max(ticket_joins, joins_ev)
    browse_without_join = max(0, views - joins_total)
    completions = outcomes.get(TicketStatus.completed.value, 0)
    cancellations = outcomes.get(TicketStatus.cancelled.value, 0)
    no_shows = outcomes.get(TicketStatus.no_show.value, 0)
    lost_demand_total = cancellations + no_shows
    leaves_total = lost_demand_total
    min_wait, max_wait = _min_max_minutes(wait_mins)
    min_serve, max_serve = _min_max_minutes(serve_mins)

    leave_rate = (
        round(100.0 * leaves_total / joins_total, 1) if joins_total > 0 else None
    )

    summary = ProviderAnalyticsSummary(
        page_views=views,
        joins=joins_total,
        completions=completions,
        cancellations=cancellations,
        no_shows=no_shows,
        abandonments=abandons,
        queue_clears=cleared,
        lost_demand_total=lost_demand_total,
        browse_without_join=browse_without_join,
        customer_left_voluntarily=abandons,
        lost_join_opportunities=lost_demand_total,
        avg_wait_minutes=_avg_minutes(wait_mins),
        avg_serve_minutes=_avg_minutes(serve_mins),
        min_wait_minutes=min_wait,
        max_wait_minutes=max_wait,
        min_serve_minutes=min_serve,
        max_serve_minutes=max_serve,
        conversion_rate_pct=(
            round(100.0 * joins_total / views, 1) if views > 0 else None
        ),
        customers_helped=completions,
        leave_rate_pct=leave_rate,
    )

    total_activity = sum(hourly_joins)
    if total_activity == 0 and views == 0 and ticket_joins == 0:
        data_quality: DataQuality = "empty"
    elif total_activity < 12:
        data_quality = "sparse"
    else:
        data_quality = "rich"

    display_joins, hourly_est = _blend_hourly(hourly_joins)
    peak_hour = (
        display_joins.index(max(display_joins)) if max(display_joins) > 0 else None
    )
    quiet_hour = None
    if max(display_joins) > 0:
        quiet_candidates = [
            i for i, v in enumerate(display_joins) if v == min(display_joins)
        ]
        quiet_hour = quiet_candidates[0]

    peak_leave_hour = (
        hourly_leaves.index(max(hourly_leaves)) if max(hourly_leaves) > 0 else None
    )

    hourly_activity = [
        TimeBucket(
            label=f"{h:02d}:00",
            hour=h,
            value=display_joins[h],
            secondary=hourly_completions[h],
            is_estimated=hourly_est and display_joins[h] != hourly_joins[h],
        )
        for h in range(24)
    ]
    hourly_leaves_buckets = [
        TimeBucket(label=f"{h:02d}:00", hour=h, value=hourly_leaves[h])
        for h in range(24)
    ]

    day_count = min(days, 14)
    daily_labels: list[str] = []
    daily_joins: list[int] = []
    daily_leaves_list: list[int] = []
    for i in range(day_count):
        d = end.date() - timedelta(days=day_count - 1 - i)
        key = d.isoformat()
        daily_labels.append(d.strftime("%b %d"))
        daily_joins.append(daily_joins_map.get(key, 0))
        daily_leaves_list.append(daily_leaves_map.get(key, 0))

    display_daily, daily_est = _blend_daily(daily_joins)
    daily_trend = [
        TimeBucket(
            label=daily_labels[i],
            value=display_daily[i],
            secondary=daily_leaves_list[i],
            is_estimated=daily_est and display_daily[i] != daily_joins[i],
        )
        for i in range(len(daily_labels))
    ]
    daily_leaves_buckets = [
        TimeBucket(label=daily_labels[i], value=daily_leaves_list[i])
        for i in range(len(daily_labels))
    ]

    weekday_activity = [
        TimeBucket(label=WEEKDAY_SHORT[i], value=weekday_joins[i])
        for i in range(7)
    ]
    weekday_leaves_buckets = [
        TimeBucket(label=WEEKDAY_SHORT[i], value=weekday_leaves[i])
        for i in range(7)
    ]

    best_weekday_idx = (
        max(range(7), key=lambda i: weekday_joins[i])
        if sum(weekday_joins) > 0
        else None
    )
    worst_weekday_idx = None
    if sum(weekday_joins) > 0:
        active_wd = [i for i, v in enumerate(weekday_joins) if v > 0]
        if active_wd:
            worst_weekday_idx = min(active_wd, key=lambda i: weekday_joins[i])

    # Per-calendar-day speed (avg wait)
    day_avg_wait: list[tuple[str, float]] = []
    for d_str, waits in daily_wait.items():
        if waits:
            day_avg_wait.append((d_str, sum(waits) / len(waits)))
    fastest_day_label = None
    slowest_day_label = None
    if day_avg_wait:
        fastest = min(day_avg_wait, key=lambda x: x[1])
        slowest = max(day_avg_wait, key=lambda x: x[1])
        fastest_day_label = date.fromisoformat(fastest[0]).strftime("%b %d")
        slowest_day_label = date.fromisoformat(slowest[0]).strftime("%b %d")

    period_start = start.date()
    period_end = end.date()
    streaks = _compute_streaks(
        dict(daily_joins_map),
        period_start=period_start,
        period_end=period_end,
        queue_clears=cleared,
    )

    peak_slots: list[AnalyticsPeakSlot] = []
    for slot in (
        _slot_peak(
            display_joins,
            kind="join",
            metric_label="joins",
            label_fn=lambda i: _format_hour_12(i),
            direction="best",
            explanation_fn=lambda i, v: f"{v} join(s) around this hour — your busiest time.",
        ),
        _slot_peak(
            display_joins,
            kind="join",
            metric_label="joins",
            label_fn=lambda i: _format_hour_12(i),
            direction="worst",
            explanation_fn=lambda i, v: f"Only {v} join(s) — your quietest hour for new customers.",
        ),
        _slot_peak(
            hourly_leaves,
            kind="leave",
            metric_label="left queue",
            label_fn=lambda i: _format_hour_12(i),
            direction="best",
            explanation_fn=lambda i, v: f"{v} customer(s) left without finishing — peak leave time.",
        ),
        _slot_peak(
            weekday_joins,
            kind="day",
            metric_label="joins",
            label_fn=lambda i: WEEKDAY_FULL[i],
            direction="best",
            explanation_fn=lambda i, v: f"{v} join(s) on this weekday — plan extra capacity.",
        ),
        _slot_peak(
            weekday_joins,
            kind="day",
            metric_label="joins",
            label_fn=lambda i: WEEKDAY_FULL[i],
            direction="worst",
            explanation_fn=lambda i, v: f"{v} join(s) — slowest weekday in this period.",
        ),
    ):
        if slot:
            peak_slots.append(slot)

    half = len(daily_joins) // 2
    comparisons = _build_comparisons(
        weekday_joins=weekday_joins,
        daily_joins_first_half=sum(daily_joins[:half]),
        daily_joins_second_half=sum(daily_joins[half:]),
        period_label=f"{days}-day window",
    )

    highlights = _build_highlights(
        summary=summary,
        peak_hour=peak_hour,
        quiet_hour=quiet_hour,
        peak_leave_hour=peak_leave_hour,
        best_weekday_idx=best_weekday_idx,
        worst_weekday_idx=worst_weekday_idx,
        weekday_joins=weekday_joins,
        fastest_day_label=fastest_day_label,
        slowest_day_label=slowest_day_label,
        data_quality=data_quality,
    )

    service_lines = [
        ProviderAnalyticsServiceLine(
            service_item_id=sid,
            service_name=service_names.get(sid, "Service"),
            joins=stats["joins"],
            completed=stats["completed"],
            cancelled=stats["cancelled"],
            no_show=stats["no_show"],
        )
        for sid, stats in sorted(
            by_service.items(), key=lambda x: x[1]["joins"], reverse=True
        )
    ]

    insights = _insights(
        summary=summary,
        peak_hour=peak_hour,
        quiet_hour=quiet_hour,
        peak_leave_hour=peak_leave_hour,
        data_quality=data_quality,
        streaks=streaks,
    )

    narrative = _narrative(
        summary=summary,
        streaks=streaks,
        peak_hour=peak_hour,
        data_quality=data_quality,
        range_days=days,
    )

    return ProviderAnalyticsPublic(
        provider_id=provider_id,
        service_item_id=service_item_id,
        range_days=days,
        since=start,
        until=end,
        data_quality=data_quality,
        uses_estimates=hourly_est or daily_est,
        narrative_summary=narrative,
        summary=summary,
        hourly_activity=hourly_activity,
        hourly_leaves=hourly_leaves_buckets,
        daily_trend=daily_trend,
        daily_leaves=daily_leaves_buckets,
        weekday_activity=weekday_activity,
        weekday_leaves=weekday_leaves_buckets,
        ticket_outcomes=dict(outcomes),
        join_sources=dict(by_source),
        service_lines=service_lines,
        insights=insights,
        highlights=highlights,
        peak_slots=peak_slots,
        streaks=streaks,
        comparisons=comparisons,
        peak_hour=peak_hour,
        quiet_hour=quiet_hour,
        peak_leave_hour=peak_leave_hour,
    )
