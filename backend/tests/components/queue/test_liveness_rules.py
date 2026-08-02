"""FR-05 liveness decisions, exercised without a DB.

The evidence bar lives here, so this is where it is pinned down from both
sides: a deliberate check-in always counts (with or without a location
fix), background polling never does, and it takes consecutive unconfirmed
windows to reach a flag.
"""

from datetime import datetime, timedelta, timezone

import pytest

from werefa.queue.domain import liveness_rules
from werefa.queue.domain.liveness_rules import (
    LivenessSnapshot,
    WindowOutcome,
)
from werefa.shared.enums import (
    LivenessAction,
    LivenessState,
    NotificationReach,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
GRACE = 600
MAX_HOLDS = 2


def _snap(**kw: object) -> LivenessSnapshot:
    base: dict[str, object] = {
        "state": LivenessState.awaiting.value,
        "now": NOW,
        "in_top_k": True,
    }
    base.update(kw)
    return LivenessSnapshot(**base)  # type: ignore[arg-type]


def _classify(snapshot: LivenessSnapshot, misses_before_flag: int = 2):
    return liveness_rules.classify_window(
        snapshot, misses_before_flag=misses_before_flag
    )


def _recommend(snapshot: LivenessSnapshot, max_holds: int = MAX_HOLDS):
    return liveness_rules.recommend(
        snapshot, activity_grace_seconds=GRACE, max_holds=max_holds
    )


# --- window classification -------------------------------------------------


def test_window_not_yet_expired_is_a_no_op() -> None:
    outcome = _classify(_snap(deadline_at=NOW + timedelta(seconds=30)))
    assert outcome == WindowOutcome.within_window


def test_no_deadline_is_a_no_op() -> None:
    assert _classify(_snap(deadline_at=None)) == WindowOutcome.within_window


def test_first_missed_window_warns_rather_than_flags() -> None:
    """One miss is a nudge. Phones sleep; that is not a no-show."""
    outcome = _classify(_snap(deadline_at=NOW - timedelta(seconds=1), misses=0))
    assert outcome == WindowOutcome.warn


def test_second_consecutive_missed_window_flags() -> None:
    outcome = _classify(_snap(deadline_at=NOW - timedelta(seconds=1), misses=1))
    assert outcome == WindowOutcome.flag


def test_background_polling_does_not_rescue_an_expired_window() -> None:
    """The tightening: a chatty app is not a customer on their way.

    An app left open on a kitchen table polls exactly like one in a taxi.
    If that cleared the window, the silent absentee we most need staff to
    see coming would be the one case the system could never surface.
    """
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            last_seen_at=NOW - timedelta(seconds=5),
            misses=1,
        )
    )
    assert outcome == WindowOutcome.flag


def test_polling_does_not_soften_the_first_miss_either() -> None:
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            last_seen_at=NOW - timedelta(seconds=5),
            misses=0,
        )
    )
    assert outcome == WindowOutcome.warn


def test_misses_before_flag_of_one_flags_immediately() -> None:
    """The old single-strike behaviour stays reachable by config."""
    outcome = _classify(
        _snap(deadline_at=NOW - timedelta(seconds=1), misses=0),
        misses_before_flag=1,
    )
    assert outcome == WindowOutcome.flag


# --- recommendations -------------------------------------------------------


def test_outside_top_k_has_nothing_to_decide() -> None:
    rec = _recommend(_snap(in_top_k=False))
    assert rec.action == LivenessAction.none


def test_idle_state_has_nothing_to_decide() -> None:
    rec = _recommend(_snap(state=LivenessState.idle.value))
    assert rec.action == LivenessAction.none


def test_recent_location_fix_recommends_proceed() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.ok.value,
            last_ping_at=NOW - timedelta(seconds=10),
            last_seen_at=NOW - timedelta(seconds=10),
        )
    )
    assert rec.action == LivenessAction.proceed
    assert not rec.can_hold


def test_check_in_without_a_fix_recommends_verify_not_hold() -> None:
    """A failed GPS read must never produce a hold recommendation.

    They answered the question we asked; the location stack is not their
    responsibility.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.ok.value,
            last_seen_at=NOW - timedelta(seconds=20),
        )
    )
    assert rec.action == LivenessAction.verify
    assert not rec.can_hold
    assert "not a no-show" in rec.reason


def test_flagged_with_no_check_in_recommends_hold() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            last_ping_at=NOW - timedelta(minutes=25),
            misses=2,
        )
    )
    assert rec.action == LivenessAction.hold
    assert rec.can_hold
    assert "25 min" in rec.reason


def test_flagged_with_no_contact_at_all_still_recommends_hold() -> None:
    rec = _recommend(_snap(state=LivenessState.flagged.value, misses=2))
    assert rec.action == LivenessAction.hold
    assert rec.can_hold


def test_a_flag_survives_a_chatty_app() -> None:
    """Polling colours the wording; it must not downgrade the action."""
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            last_seen_at=NOW - timedelta(seconds=5),
            last_ping_at=NOW - timedelta(minutes=30),
            misses=2,
        )
    )
    assert rec.action == LivenessAction.hold
    assert rec.can_hold
    assert "online but silent" in rec.reason


def test_polling_before_a_flag_is_reported_but_not_reassuring() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.awaiting.value,
            last_seen_at=NOW - timedelta(seconds=5),
        )
    )
    assert rec.action == LivenessAction.verify
    assert "has not confirmed" in rec.reason


def test_flagged_after_holds_are_spent_recommends_calling_them() -> None:
    """Holds are finite, so the line cannot be stalled indefinitely.

    Once spent the answer is "call them" — the only route that can end in
    a strike, and it takes a human pressing the button.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            last_seen_at=NOW - timedelta(minutes=40),
            hold_count=MAX_HOLDS,
        )
    )
    assert rec.action == LivenessAction.proceed
    assert not rec.can_hold
    assert "no-show" in rec.reason


def test_held_and_silent_says_keep_holding() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.awaiting.value,
            hold_until=NOW + timedelta(minutes=3),
            hold_count=1,
        )
    )
    assert rec.action == LivenessAction.hold
    assert not rec.can_hold


def test_an_app_waking_up_mid_hold_does_not_end_the_hold() -> None:
    """Nothing but the timer or an explicit release ends a park.

    Recommending release off background traffic would hand the spot back
    to someone who has still told us nothing.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.awaiting.value,
            hold_until=NOW + timedelta(minutes=3),
            last_seen_at=NOW - timedelta(seconds=5),
            hold_count=1,
        )
    )
    assert rec.action == LivenessAction.hold


def test_a_customer_who_checked_in_is_no_longer_parked() -> None:
    """The state a check-in leaves behind must read as callable.

    ``record_position_ping`` clears ``hold_until`` outright, so a
    confirmed customer never reaches the held branch — and staff are told
    to call them rather than to keep serving others. This pins the pair
    together: if the service ever stopped clearing the hold, the board
    would go back to saying "keep serving others" about someone the
    counter can serve right now.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.ok.value,
            hold_until=None,
            hold_count=1,
            last_ping_at=NOW - timedelta(seconds=5),
        )
    )
    assert rec.action == LivenessAction.proceed


def test_a_park_outranks_falling_out_of_the_watch_window() -> None:
    """A parked spot is never "not near the front yet".

    The line moving on — a VIP bump, other customers served — drops a
    ticket out of top-K, and the old ordering answered ``none`` for it.
    Staff would have read that as "nothing to do here" about a spot the
    business had promised to keep.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.idle.value,
            in_top_k=False,
            hold_until=NOW + timedelta(minutes=3),
            hold_count=1,
        )
    )
    assert rec.action == LivenessAction.hold
    assert "held" in rec.reason


def test_expired_hold_no_longer_reads_as_held() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            hold_until=NOW - timedelta(seconds=1),
            hold_count=1,
            last_ping_at=NOW - timedelta(minutes=30),
        )
    )
    assert rec.action == LivenessAction.hold
    assert rec.can_hold


def test_waiting_on_first_checkin_is_not_actionable() -> None:
    rec = _recommend(_snap(state=LivenessState.awaiting.value))
    assert rec.action == LivenessAction.verify
    assert not rec.can_hold


@pytest.mark.parametrize("holds", [0, 1])
def test_can_hold_is_capped(holds: int) -> None:
    assert liveness_rules.can_hold(_snap(hold_count=holds), max_holds=2)


def test_can_hold_is_false_once_spent() -> None:
    assert not liveness_rules.can_hold(_snap(hold_count=2), max_holds=2)


def test_activity_is_not_read_from_the_future() -> None:
    """Clock skew on a client must not manufacture presence."""
    assert not liveness_rules.has_passive_activity(
        _snap(last_seen_at=NOW + timedelta(minutes=5)),
        activity_grace_seconds=GRACE,
    )


# --- silence only counts if they were asked --------------------------------
#
# Every rule above reads a missing check-in as an answer. It is not one
# when the prompt never arrived — the carrier rejected the text, or the
# alert only ever landed on the ``logger`` backstop because the customer
# has no reachable channel at all. Before the notification ledger could
# tell those apart, our delivery failure was scored against the customer:
# two silent windows, a flag, and staff called them and took the no-show.


def test_an_undelivered_prompt_costs_no_miss() -> None:
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            misses=0,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert outcome == WindowOutcome.unreachable


def test_undelivered_prompts_never_accumulate_into_a_flag() -> None:
    """Checked ahead of the miss count, so weight of numbers cannot flag."""
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            misses=5,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert outcome == WindowOutcome.unreachable


def test_a_confirmed_prompt_still_flags_on_the_second_miss() -> None:
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            misses=1,
            warning_reach=NotificationReach.confirmed,
        )
    )
    assert outcome == WindowOutcome.flag


def test_an_unconfirmed_prompt_gets_no_benefit_of_the_doubt() -> None:
    """Ignorance is not proof.

    A row still in flight, or one a gateway accepted without reporting
    back, behaves exactly as it always did — otherwise every unlucky
    moment of not-knowing becomes an excuse and a genuine absentee is
    unflaggable.
    """
    outcome = _classify(
        _snap(
            deadline_at=NOW - timedelta(seconds=1),
            misses=1,
            warning_reach=NotificationReach.unconfirmed,
        )
    )
    assert outcome == WindowOutcome.flag


def test_an_undelivered_prompt_is_not_a_reason_to_skip_an_unexpired_window() -> None:
    outcome = _classify(
        _snap(
            deadline_at=NOW + timedelta(minutes=5),
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert outcome == WindowOutcome.within_window


def test_staff_are_told_we_could_not_reach_them_not_that_they_went_quiet() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            last_ping_at=NOW - timedelta(minutes=25),
            misses=2,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert rec.action == LivenessAction.hold
    assert rec.can_hold
    # The wording is the point: "no check-in for 25 min" reads as someone
    # ignoring their phone, and it looks identical when the truth is that
    # every text we sent bounced.
    assert "could not get a message" in rec.reason
    assert "25 min" not in rec.reason


def test_unreachable_with_holds_spent_still_hands_over_to_a_human() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            hold_count=MAX_HOLDS,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert rec.action == LivenessAction.proceed
    assert not rec.can_hold
    assert "call them" in rec.reason


def test_a_customer_who_checked_in_is_not_second_guessed_by_delivery() -> None:
    """They answered; whether a later prompt landed is beside the point."""
    rec = _recommend(
        _snap(
            state=LivenessState.ok.value,
            last_ping_at=NOW - timedelta(seconds=30),
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert rec.action == LivenessAction.proceed
    assert "Checked in with location" in rec.reason


def test_a_held_spot_outranks_an_undelivered_prompt() -> None:
    """A live park is a commitment staff already made and must still see."""
    rec = _recommend(
        _snap(
            state=LivenessState.flagged.value,
            hold_until=NOW + timedelta(minutes=4),
            hold_count=1,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert rec.action == LivenessAction.hold
    assert "Spot is held" in rec.reason


def test_an_unreachable_customer_far_from_the_front_is_still_nobodys_problem() -> None:
    rec = _recommend(
        _snap(in_top_k=False, warning_reach=NotificationReach.not_reached)
    )
    assert rec.action == LivenessAction.none


def test_a_park_we_granted_because_we_could_not_reach_them_says_so() -> None:
    """"Until they check in" is the wrong instruction here.

    It tells staff to wait for an answer to a question the customer was
    never asked, so the only thing that ever happens is the hold expiring.
    """
    rec = _recommend(
        _snap(
            state=LivenessState.awaiting.value,
            hold_until=NOW + timedelta(minutes=4),
            hold_count=1,
            warning_reach=NotificationReach.not_reached,
        )
    )
    assert rec.action == LivenessAction.hold
    assert "could not get a message" in rec.reason
    assert "call them" in rec.reason


def test_an_ordinary_park_keeps_its_ordinary_wording() -> None:
    rec = _recommend(
        _snap(
            state=LivenessState.awaiting.value,
            hold_until=NOW + timedelta(minutes=4),
            hold_count=1,
            warning_reach=NotificationReach.confirmed,
        )
    )
    assert rec.action == LivenessAction.hold
    assert "until they check in" in rec.reason
