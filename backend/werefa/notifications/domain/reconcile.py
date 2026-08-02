"""Pure rules for what to do with a notification the worker never finished (FR-07).

The delivery worker is deliberately non-durable: jobs live in memory, so a
crash or a restart leaves the ledger row it was going to resolve sitting at
``queued`` forever. That row is *visible*, which is already better than the
silent loss inline sending had — but nothing ever went back for it, so a
customer who was owed a text simply never got one and nothing said so.

Reconciliation closes that. This module holds the decision only: no DB, no
clock, no settings, so "would we really re-text somebody twenty minutes
late?" is answerable in a unit test instead of inferred from a worker's
behaviour.

Four things shape the rule.

**A send we may already have made is never made again.** ``queued`` on its
own does not mean "never sent" — the worker resolves the row *after* the
gateway answers, so a process killed in between leaves exactly the same
row behind whether the text went out or not. The ledger's
``delivery_attempts`` closes that gap: the worker commits it before
calling the provider, so ``0`` is a genuine proof that the job never got
that far, and anything else means a message might be sitting on somebody's
phone right now. Only the provable case is re-sent. The rest are resolved
without contacting anyone — we cannot confirm those, and an unconfirmed
delivery is a much smaller problem than a duplicate one.

**Age has a floor.** A row queued moments ago is most likely in flight
right now — this process is not necessarily the only one, and a rolling
deploy runs old and new side by side. Below the floor we leave it alone;
above it, no live worker can still legitimately own the row, because the
whole retry budget plus the overflow parking TTL has elapsed.

**Most of these alerts expire.** "You're next", "head to the counter",
"we're serving you now" are all claims about where the line is *right
now*. Delivering one late is not a partial win, it is a lie that sends
someone walking to a counter that served them ages ago — the same
reasoning that makes the delivery queue drop parked jobs after
``NOTIFICATION_DELIVERY_SHED_TTL_SECONDS``. So a re-send is reserved for
the kinds whose message is still true whenever it lands, and everything
else is recorded ``failed`` without touching a gateway.

**The durable list is opt-in.** A kind nobody has classified falls to
``fail``, so adding a ``NotificationKind`` can never silently enrol it in
late re-sends.
"""

from __future__ import annotations

from enum import Enum

from werefa.shared.enums import NotificationKind


class ZombieAction(str, Enum):
    """What reconciliation should do with one stuck ``queued`` row."""

    leave = "leave"
    """Too young to judge — a worker somewhere may still be on it."""

    retry = "retry"
    """Hand it back to the delivery worker; the message still holds."""

    fail = "fail"
    """Resolve the row ``failed`` without sending. Either the alert has
    gone stale, or it is too old to be worth anything at all."""


DURABLE_KINDS: frozenset[NotificationKind] = frozenset(
    {
        # "The line closed for the day and your ticket is closed" is the
        # one alert you most want to arrive late — nothing about it stops
        # being true, and a customer who never hears it keeps waiting.
        NotificationKind.queue_cleared,
        # A staff message is attributed prose, not a position claim. It
        # reads a little stale on arrival; it does not mislead.
        NotificationKind.line_chat_update,
    }
)
"""Kinds still worth sending after a restart.

Everything else is a statement about the customer's position in the line
at the moment it was raised — see the module docstring for why those are
failed rather than re-sent.
"""


def decide_reconcile(
    *,
    kind: NotificationKind | None,
    age_seconds: float | None,
    delivery_attempts: int,
    min_age_seconds: float,
    max_age_seconds: float,
) -> ZombieAction:
    """Decide the fate of a ``queued`` row that is ``age_seconds`` old.

    ``delivery_attempts`` is the ledger's count of sends already handed to
    a gateway. Anything above zero rules out a re-send outright, ahead of
    every other consideration — a duplicate text is a worse outcome than
    an unconfirmed one, and no amount of freshness makes it better.

    ``kind`` is ``None`` when the ledger holds a value this build does not
    recognise (a rollback to an older image, say), and ``age_seconds`` is
    ``None`` when the row has no ``created_at`` to measure. Both resolve to
    ``fail``: unknown is never a licence to text somebody.

    ``max_age_seconds`` below ``min_age_seconds`` is a legitimate way to
    configure "never retry, only resolve" — the bands simply stop
    overlapping, and every zombie comes back ``fail``.
    """
    if age_seconds is None:
        return ZombieAction.fail
    if age_seconds < min_age_seconds:
        # Still too early to say anything, including whether that attempt
        # is going to resolve itself a second from now.
        return ZombieAction.leave
    if delivery_attempts > 0:
        return ZombieAction.fail
    if age_seconds > max_age_seconds:
        # Old enough that even a durable message is archaeology.
        return ZombieAction.fail
    if kind is None or kind not in DURABLE_KINDS:
        return ZombieAction.fail
    return ZombieAction.retry
