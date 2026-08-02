"""FR-05 liveness decisions, free of DB and HTTP.

Presence has two tiers, and only one of them clears a grace window:

* **Confirmation** — the customer deliberately tapped "I'm on my way".
  This is the only signal that answers the question we are actually
  asking, so it is the only one that resets the window. Crucially it does
  *not* require a location fix: a device that cannot get a fix still
  produces a real confirmation, so a flat GPS never costs anyone a spot.
* **Passive activity** — a background poll from the customer's app. It
  proves a process is running on a phone somewhere. It does not prove
  anyone read anything, and an app left open on a kitchen table would
  otherwise make a genuine absentee permanently unflaggable. So it is
  recorded, shown to staff, and given no power over the state machine.

Two questions live here, separately on purpose:

1. *What did we observe?* — :func:`classify_window` turns an expired grace
   window into a warning or, after enough consecutive misses, a flag.
2. *What should staff do?* — :func:`recommend` maps the observation onto a
   concrete counter action. The old flow stopped after (1) and left staff
   holding a red badge with no next step, which in practice meant calling
   the customer anyway and taking the no-show — the worst of both worlds
   for someone whose only sin was a flat battery.

Both questions have a precondition that went unasked for a long time:
**did the prompt actually reach them?** Every rule below reads a customer's
silence as an answer, and silence only answers a question that was heard.
An SMS the carrier never delivered, or an alert that "succeeded" on the
``logger`` backstop because the customer has no usable channel at all,
produces exactly the same silence as someone ignoring their phone — and
until the notification ledger could tell those apart
(:mod:`werefa.notifications.domain.receipts`), our delivery failure was
scored against the customer. ``LivenessSnapshot.warning_reach`` carries
the answer, and it changes both outcomes: an unreachable customer does
not accrue misses (:attr:`WindowOutcome.unreachable`), and staff are told
we could not reach them rather than that they went quiet.

Only *proof* of failure buys that leniency. A row still in flight, or one
a gateway accepted without reporting back, reads ``unconfirmed`` and
behaves exactly as before — otherwise every unlucky moment of ignorance
would become an excuse, and a genuine absentee would be unflaggable.

Neither function can strike, cancel, or reorder anything. Liveness is
advisory by construction: the only path to a strike stays the human one
(staff calls the customer, the customer does not appear). That is what
makes it safe to flag readily — a flag costs the customer a held spot,
not a penalty.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from werefa.shared.enums import LivenessAction, LivenessState, NotificationReach


class WindowOutcome(str, Enum):
    """What an evaluation of the grace window concluded."""

    # Deadline has not passed yet — nothing to do.
    within_window = "within_window"
    # A miss, but not yet enough of them. Nudge and re-arm.
    warn = "warn"
    # Enough consecutive unconfirmed windows to tell staff we have lost
    # them. Reachable no matter how busy the customer's app looks.
    flag = "flag"
    # The window expired and the prompt provably never got to them, so
    # there is nothing here for the customer to have missed. Costs no
    # miss and cannot flag; the service re-arms the window and staff are
    # told, through :func:`recommend`, to call rather than wait.
    unreachable = "unreachable"


@dataclass(frozen=True)
class LivenessSnapshot:
    """Everything the rules need about one ticket at one instant."""

    state: str
    now: datetime
    deadline_at: datetime | None = None
    last_ping_at: datetime | None = None
    last_seen_at: datetime | None = None
    misses: int = 0
    hold_until: datetime | None = None
    hold_count: int = 0
    in_top_k: bool = False

    warning_reach: NotificationReach = NotificationReach.unconfirmed
    """Whether the last prompt we sent this ticket actually landed.

    Read off the notification ledger for the most recent
    ``liveness_ping_request``/``liveness_stale`` row — see
    ``notifications.application.service.alert_reach``.

    Defaults to ``unconfirmed``, which is the pre-existing behaviour in
    every respect. A caller that does not supply it therefore gets the
    old rules rather than accidental leniency, which matters because the
    default is what every hand-built snapshot in a test starts from.
    """


@dataclass(frozen=True)
class Recommendation:
    """A staff-facing next step plus the evidence behind it."""

    action: LivenessAction
    reason: str
    can_hold: bool = False


def _age_seconds(then: datetime | None, now: datetime) -> float | None:
    if then is None:
        return None
    return (now - then).total_seconds()


def _minutes(seconds: float) -> int:
    """Round *up* to whole minutes, floored at 1.

    Staff read these numbers out loud ("no contact for 3 minutes"), so
    "0 minutes" would be worse than useless.
    """
    return max(1, int(seconds // 60) + (1 if seconds % 60 else 0))


def has_passive_activity(
    snapshot: LivenessSnapshot, *, activity_grace_seconds: int
) -> bool:
    """Has the ticket holder's app polled us recently?

    Weak evidence by design. A backgrounded app polls whether or not
    anybody is looking at it, so this only ever colours the wording staff
    see — it never clears a window and never blocks a flag. Confirmation
    is what clears a window; see :func:`classify_window`.
    """
    age = _age_seconds(snapshot.last_seen_at, snapshot.now)
    return age is not None and 0 <= age <= activity_grace_seconds


def has_recent_fix(
    snapshot: LivenessSnapshot, *, activity_grace_seconds: int
) -> bool:
    age = _age_seconds(snapshot.last_ping_at, snapshot.now)
    return age is not None and 0 <= age <= activity_grace_seconds


def is_held(snapshot: LivenessSnapshot) -> bool:
    return snapshot.hold_until is not None and snapshot.now < snapshot.hold_until


def can_hold(snapshot: LivenessSnapshot, *, max_holds: int) -> bool:
    """Holds are capped: a spot cannot be parked indefinitely.

    Otherwise one unreachable customer at the head of a busy line could be
    held all afternoon, which is just a slow way of never serving them
    while pretending we did them a favour.
    """
    return snapshot.hold_count < max_holds


def classify_window(
    snapshot: LivenessSnapshot, *, misses_before_flag: int
) -> WindowOutcome:
    """Decide what an expired (or unexpired) grace window means.

    Only a confirmation re-arms the deadline, so reaching this function
    with an expired one already means "they did not confirm". Background
    polling is deliberately absent from this decision: an app left open at
    home must not be able to hold a spot indefinitely.

    An expired window is only evidence about the *customer* if they were
    asked. When ``warning_reach`` proves the prompt never arrived — the
    carrier rejected the text, or the alert only ever reached the
    ``logger`` backstop — the window says something about our delivery
    instead, so it returns :attr:`WindowOutcome.unreachable` and costs
    them nothing. Two windows of our own silence would otherwise flag a
    customer who was never spoken to, and the flag is what sends staff
    looking for someone to hold or call.

    Note this is checked *before* the miss count, so a run of
    undelivered prompts can never accumulate into a flag by weight of
    numbers. Ignorance is not proof, though: ``unconfirmed`` (in flight,
    or accepted with no receipt) takes the ordinary path.
    """
    if snapshot.deadline_at is None or snapshot.now < snapshot.deadline_at:
        return WindowOutcome.within_window
    if snapshot.warning_reach is NotificationReach.not_reached:
        return WindowOutcome.unreachable
    if snapshot.misses + 1 >= misses_before_flag:
        return WindowOutcome.flag
    return WindowOutcome.warn


def recommend(
    snapshot: LivenessSnapshot,
    *,
    activity_grace_seconds: int,
    max_holds: int,
) -> Recommendation:
    """Map liveness evidence onto the counter action staff should take."""
    if is_held(snapshot):
        # Answered first, and before the top-K gate: a parked spot is a
        # live commitment whatever the line has done since, and staff must
        # never read "not near the front yet" about a customer they told
        # "we're holding your place".
        #
        # A check-in ends a park on its own — ``record_position_ping``
        # clears the hold — so any ticket still reaching this branch is one
        # we genuinely have not heard from. An app that merely starts
        # polling mid-hold is not the customer answering, and must not
        # hand the spot back.
        if snapshot.warning_reach is NotificationReach.not_reached:
            # Parked because we could not get a message through, most
            # likely by the sync loop rather than by a person. Staff must
            # be told which kind of hold this is: "until they check in"
            # invites waiting for an answer that cannot arrive, and the
            # hold expiring is then the only thing that ever happens.
            return Recommendation(
                LivenessAction.hold,
                "Spot is held because we could not get a message to them — "
                "keep serving others, and call them rather than waiting "
                "for a check-in they were never asked for.",
            )
        return Recommendation(
            LivenessAction.hold,
            "Spot is held — keep serving others until they check in "
            "or the hold expires.",
        )

    if not snapshot.in_top_k or snapshot.state == LivenessState.idle.value:
        return Recommendation(LivenessAction.none, "Not near the front yet.")

    if (
        snapshot.warning_reach is NotificationReach.not_reached
        and snapshot.state != LivenessState.ok.value
    ):
        # Answered ahead of the flag, because the flag reads as "they went
        # quiet on us" and this is the case where they were never spoken
        # to. Staff seeing "no check-in for 12 minutes" about a customer
        # whose phone we could not text will call them and, when nobody
        # picks up, mark the no-show — a penalty caused entirely by our
        # own undelivered message.
        #
        # ``ok`` skips this: they checked in, so whether a later prompt
        # landed is beside the point.
        #
        # The hold still comes first: a customer who never got the text is
        # exactly who a held spot is for, and it is the action that costs
        # them nothing while staff work out what happened.
        if can_hold(snapshot, max_holds=max_holds):
            return Recommendation(
                LivenessAction.hold,
                "We could not get a message to them — hold the spot and "
                "call them. Their silence is our delivery failure, not a "
                "no-show.",
                can_hold=True,
            )
        return Recommendation(
            LivenessAction.proceed,
            f"We could not get a message to them and the spot has been "
            f"held {snapshot.hold_count}x — call them, and mark no-show "
            "only if they do not appear.",
        )

    polling = has_passive_activity(
        snapshot, activity_grace_seconds=activity_grace_seconds
    )
    fresh_fix = has_recent_fix(
        snapshot, activity_grace_seconds=activity_grace_seconds
    )
    unconfirmed_for = _age_seconds(snapshot.last_ping_at, snapshot.now)

    if snapshot.state == LivenessState.flagged.value:
        # Checked *before* any activity signal: a chatty app must not talk
        # a flag back down into advice to wait.
        silence = (
            f"No check-in for {_minutes(unconfirmed_for)} min"
            if unconfirmed_for is not None
            else "Never checked in"
        )
        if polling:
            silence += " (their app is online but silent)"
        if can_hold(snapshot, max_holds=max_holds):
            return Recommendation(
                LivenessAction.hold,
                f"{silence} — hold the spot and serve the next customer.",
                can_hold=True,
            )
        # Holds are spent. Calling them is now the honest next step: it is
        # the only way to find out, and it is the only path that can end in
        # a strike — which is exactly why a person, not a timer, triggers it.
        return Recommendation(
            LivenessAction.proceed,
            f"Held {snapshot.hold_count}x already — call them, "
            "and mark no-show only if they do not appear.",
        )

    if snapshot.state == LivenessState.ok.value:
        if fresh_fix:
            return Recommendation(
                LivenessAction.proceed,
                "Checked in with location — call as normal.",
            )
        # Confirmed without a usable fix. Full credit: they answered the
        # question we asked, and their GPS is not their fault.
        return Recommendation(
            LivenessAction.verify,
            "Checked in without a location fix — call as normal, "
            "a failed GPS read is not a no-show.",
        )

    waited = (
        f"Waiting on their check-in ({_minutes(unconfirmed_for)} min)"
        if unconfirmed_for is not None
        else "Waiting on their first check-in"
    )
    if polling:
        waited += "; their app is online but has not confirmed"
    return Recommendation(LivenessAction.verify, f"{waited} — no action yet.")
