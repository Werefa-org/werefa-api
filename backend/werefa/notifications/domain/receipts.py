"""What a delivery receipt is allowed to say about a ledger row (FR-07).

Two questions live here, both pure — no DB, no HTTP, no vendor — so the
policy is readable without a webhook and a Twilio account.

**Can this receipt change the row?** :func:`decide_receipt`. Until now the
answer was moot, because acceptance *was* the answer: the worker wrote
``delivered`` the moment Twilio returned a 201 and nothing ever looked
again. A 201 means Twilio queued the message. It does not mean a carrier
accepted it, that the handset exists, that the number is not barred, or
that anybody read it — Twilio reports all of that later, on the status
callback we were not asking for. So a text to a disconnected number and a
text somebody acted on were the same row.

**Did the customer actually get it?** :func:`reach_of`. This one is asked
by FR-05 liveness, which concludes things from a customer's silence, and
the ledger has always had a trap waiting for it: ``_user_prefs`` appends
the ``logger`` backstop to every preference list and ``LoggerNotifier``
never fails, so a dispatch that reached nobody still ends ``delivered``.
Reading ``status`` alone therefore says "we told them" about a customer we
demonstrably did not tell. ``channel`` is the other half of the answer.

Three rules shape both functions.

**Ignorance is not proof — but it expires.** A row still in flight, or
one a gateway has only just accepted, reads ``unconfirmed``: leniency is
spent against evidence that we failed, not against the absence of
evidence that we succeeded. That holds for as long as somebody might
still answer. Once the wait is longer than any healthy receipt takes, an
unanswered row *is* the evidence — nothing came back, so we cannot show
the customer was told, and pretending the question is still open would
let one misconfigured webhook quietly restore the old unfairness for
everybody.

**Receipts only ever settle their own channel.** A row that fell through
to email, or that a shed job settled on a local channel, is not a
statement about SMS any more, and a carrier callback arriving afterwards
must not rewrite it. The channel gate is what keeps the overflow path
(``_shed_to_local_channel``) and the receipt path from fighting over the
same row.

**A confirmed delivery is never walked back.** ``delivered`` on the
receipt-issuing channel is the strongest thing the system can know, and
callbacks can arrive late, duplicated, or out of order. Anything that
would downgrade it is dropped and logged by the caller instead.
"""

from __future__ import annotations

from enum import Enum

from werefa.shared.enums import (
    NotificationChannel,
    NotificationReach,
    NotificationStatus,
)


class ReceiptOutcome(str, Enum):
    """A carrier's verdict, stripped of whose catalogue it came from.

    Adapters map their vendor's status vocabulary onto these three (see
    ``sms/twilio.py``), for the same reason :class:`SmsResult` exists:
    the ledger should not learn what ``undelivered`` versus ``failed``
    means at Twilio, only whether the message arrived.
    """

    delivered = "delivered"
    """It reached the handset."""

    failed = "failed"
    """It will not: rejected, undeliverable, dropped by the carrier."""

    in_flight = "in_flight"
    """Still moving. Twilio reports these too (``queued``, ``sending``,
    ``sent``) and they carry no news, so they are dropped rather than
    written — a row that keeps being rewritten with "not yet" is noise
    with a lock on it."""


RECEIPT_CHANNELS: frozenset[NotificationChannel] = frozenset(
    {NotificationChannel.sms}
)
"""Channels whose delivery can be confirmed after the fact.

Email is remote too, but SMTP hands back nothing comparable — a bounce
comes back as its own asynchronous mail, not a callback keyed to our row.
So an email row never reaches ``delivered`` at all: it stops at ``sent``,
and ages out from there like any other unanswered wait.
"""


CUSTOMER_FACING_CHANNELS: frozenset[NotificationChannel] = frozenset(
    {
        NotificationChannel.websocket,
        NotificationChannel.email,
        NotificationChannel.push,
        NotificationChannel.sms,
    }
)
"""Channels that put the message in front of a person.

``logger`` is deliberately absent. It is the always-succeeds backstop
that guarantees every dispatch leaves a ledger row, which makes it the
one channel whose ``delivered`` is a statement about *us* rather than
about the customer.
"""


#: There is deliberately no "these channels only ever mean acceptance"
#: table here. Acceptance is a *status* — ``sent`` — written by the
#: notifier that knows, not a property of a channel guessed at by the
#: reader. Every channel that cannot show a person received the message
#: says so at the source: SMS awaiting a carrier receipt, email once the
#: relay takes it, a websocket publish whose audience is unknowable
#: behind Redis. A channel lookup would have to be kept in sync with
#: their behaviour by hand, and would still be wrong for the one case
#: that matters most — a websocket publish that *did* reach live
#: subscribers, which is a real delivery.


def decide_receipt(
    *,
    current_status: NotificationStatus | None,
    current_channel: NotificationChannel | None,
    receipt: ReceiptOutcome,
) -> NotificationStatus | None:
    """The status this receipt should write, or ``None`` to leave the row.

    ``None`` covers every "not ours to touch" case and is not an error:
    receipts for rows that moved on, duplicates of one we already applied,
    and the intermediate hops Twilio reports on the way.

    ``current_status`` / ``current_channel`` are ``None`` when the ledger
    holds a value this build does not recognise, which resolves to
    ``None`` — an unreadable row is not one to start rewriting.
    """
    if current_channel is None or current_channel not in RECEIPT_CHANNELS:
        # Fell through to another channel, was settled by the overload
        # shed path, or was never a receipt-issuing channel at all.
        return None
    if receipt is ReceiptOutcome.in_flight:
        return None
    if current_status is None:
        return None
    if current_status is NotificationStatus.skipped:
        # The dispatcher decided this channel was not used. A callback
        # naming it contradicts the row's own history; leave it be.
        return None

    if receipt is ReceiptOutcome.delivered:
        if current_status is NotificationStatus.delivered:
            return None  # already settled the same way; duplicate callback
        # Includes a row still reading ``queued``: a receipt cannot exist
        # unless the send happened, so it outranks our own bookkeeping,
        # and it also covers the narrow race where a fast carrier reports
        # back before the worker has committed ``sent``.
        return NotificationStatus.delivered

    if current_status is NotificationStatus.delivered:
        # Never walk a confirmed delivery back. Callbacks arrive late,
        # duplicated and out of order; "it arrived" is the one conclusion
        # a later message cannot improve on.
        return None
    if current_status is NotificationStatus.failed:
        return None  # already failed; nothing new to record
    return NotificationStatus.failed


PENDING_STATUSES: frozenset[NotificationStatus] = frozenset(
    {NotificationStatus.queued, NotificationStatus.sent}
)
"""Statuses that mean "somebody still owes us an answer".

``queued`` is owed by the delivery worker, ``sent`` by the carrier. Both
are honest unknowns *for a while* — and neither stays one, which is what
:func:`reach_of` takes ``age_seconds`` for.
"""


def reach_of(
    channel: NotificationChannel | None,
    status: NotificationStatus | None,
    *,
    age_seconds: float | None = None,
    resolution_grace_seconds: float | None = None,
) -> NotificationReach:
    """Did this ledger row actually put its message in front of anyone?

    Answered from the pair, never from ``status`` alone — see the module
    docstring for why ``delivered`` on ``logger`` means nobody was told.

    ``age_seconds`` closes the gap where "we do not know yet" quietly
    became "we will never know". A row at ``sent`` is waiting on a
    carrier receipt and a row at ``queued`` is waiting on the delivery
    worker; both arrive in seconds when the system is healthy. Past
    ``resolution_grace_seconds`` the wait is not pending any more, it is
    *failed silently* — a webhook URL that was never reachable, a process
    that died holding the job — and treating it as an open question
    forever means the commonest deployment mistake (a misconfigured
    status callback) puts every customer back to being flagged on our
    silence. So an over-age pending row reads ``not_reached``: we cannot
    show anybody was told, which is the claim the callers actually need.

    Both parameters must be supplied for the ageing to apply. A caller
    that omits them gets the pre-existing "pending is unknown" reading —
    the conservative default, and the right one for a caller that has no
    clock.

    Unreadable values resolve to :attr:`NotificationReach.unconfirmed`
    rather than ``not_reached``: callers use ``not_reached`` to excuse a
    customer's silence, and a row we cannot parse is not evidence of
    anything.
    """
    if channel is None or status is None:
        return NotificationReach.unconfirmed
    if channel not in CUSTOMER_FACING_CHANNELS:
        return NotificationReach.not_reached
    if status in (NotificationStatus.failed, NotificationStatus.skipped):
        return NotificationReach.not_reached
    if status is NotificationStatus.delivered:
        # ``delivered`` now means a person's device took it, on every
        # channel: acceptance-without-arrival is recorded as ``sent``.
        return NotificationReach.confirmed
    if (
        status in PENDING_STATUSES
        and age_seconds is not None
        and resolution_grace_seconds is not None
        and age_seconds > resolution_grace_seconds
    ):
        return NotificationReach.not_reached
    return NotificationReach.unconfirmed


__all__ = [
    "CUSTOMER_FACING_CHANNELS",
    "PENDING_STATUSES",
    "RECEIPT_CHANNELS",
    "ReceiptOutcome",
    "decide_receipt",
    "reach_of",
]
