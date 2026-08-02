"""Delivery-receipt policy, without a webhook or a Twilio account.

Two rules are being pinned down here and they pull in opposite
directions, which is the whole reason they are worth a test file.

A receipt must be able to correct the ledger — that is the point of
asking for one — so ``sent`` yields to whatever the carrier says. But it
must not be able to *undo* a delivery: callbacks arrive late, duplicated
and out of order, and "it arrived" is the one conclusion a later message
cannot improve on.

The second half, :func:`reach_of`, is what FR-05 liveness reads before
deciding a silent customer ignored us. Its most important case is the
least obvious: a row reading ``delivered`` on the ``logger`` channel is a
complete success by the dispatcher's standards and told the customer
absolutely nothing.
"""

from __future__ import annotations

import pytest

from werefa.notifications.domain.receipts import (
    ReceiptOutcome,
    decide_receipt,
    reach_of,
)
from werefa.shared.enums import (
    NotificationChannel,
    NotificationReach,
    NotificationStatus,
)

SMS = NotificationChannel.sms


def _decide(
    status: NotificationStatus | None,
    receipt: ReceiptOutcome,
    channel: NotificationChannel | None = SMS,
) -> NotificationStatus | None:
    return decide_receipt(
        current_status=status, current_channel=channel, receipt=receipt
    )


# --- what a receipt may write --------------------------------------------


def test_a_delivered_receipt_settles_a_sent_row() -> None:
    assert (
        _decide(NotificationStatus.sent, ReceiptOutcome.delivered)
        is NotificationStatus.delivered
    )


def test_a_failed_receipt_settles_a_sent_row() -> None:
    assert (
        _decide(NotificationStatus.sent, ReceiptOutcome.failed)
        is NotificationStatus.failed
    )


def test_intermediate_callbacks_change_nothing() -> None:
    # Twilio reports 'sending'/'sent' on the way. They carry no news, and
    # rewriting the row with "not yet" on each one is churn with a row
    # lock attached.
    assert _decide(NotificationStatus.sent, ReceiptOutcome.in_flight) is None


def test_a_receipt_can_beat_the_worker_to_the_row() -> None:
    # The worker commits 'sent' just after the gateway answers, so a fast
    # carrier can report back first. A receipt cannot exist unless the
    # send happened, so it outranks our own bookkeeping.
    assert (
        _decide(NotificationStatus.queued, ReceiptOutcome.delivered)
        is NotificationStatus.delivered
    )
    assert (
        _decide(NotificationStatus.queued, ReceiptOutcome.failed)
        is NotificationStatus.failed
    )


def test_a_confirmed_delivery_is_never_walked_back() -> None:
    assert _decide(NotificationStatus.delivered, ReceiptOutcome.failed) is None


def test_a_duplicate_delivered_callback_is_a_no_op() -> None:
    assert (
        _decide(NotificationStatus.delivered, ReceiptOutcome.delivered) is None
    )


def test_a_late_success_still_corrects_a_failed_row() -> None:
    # The reverse of the rule above, and deliberately not symmetric: the
    # customer having received it is better news than our record of not
    # knowing, and out-of-order callbacks are real.
    assert (
        _decide(NotificationStatus.failed, ReceiptOutcome.delivered)
        is NotificationStatus.delivered
    )


def test_a_second_failure_callback_changes_nothing() -> None:
    assert _decide(NotificationStatus.failed, ReceiptOutcome.failed) is None


@pytest.mark.parametrize(
    "channel",
    [
        NotificationChannel.email,
        NotificationChannel.websocket,
        NotificationChannel.logger,
        None,
    ],
)
def test_a_row_that_moved_on_is_not_smss_to_settle(
    channel: NotificationChannel | None,
) -> None:
    # The send fell through to another channel, or an overload shed
    # settled it locally. A carrier callback arriving afterwards is about
    # a message this row no longer records.
    assert _decide(NotificationStatus.delivered, ReceiptOutcome.failed, channel) is None
    assert _decide(NotificationStatus.sent, ReceiptOutcome.delivered, channel) is None


def test_a_skipped_row_is_left_alone() -> None:
    # The dispatcher recorded that this channel was not used; a callback
    # naming it contradicts the row's own history.
    assert _decide(NotificationStatus.skipped, ReceiptOutcome.failed) is None


def test_an_unreadable_status_is_not_rewritten() -> None:
    assert _decide(None, ReceiptOutcome.delivered) is None


# --- did the customer actually get it? -----------------------------------


def test_a_confirmed_sms_reached_them() -> None:
    assert (
        reach_of(SMS, NotificationStatus.delivered)
        is NotificationReach.confirmed
    )


def test_an_accepted_sms_with_no_receipt_yet_is_unknown() -> None:
    assert reach_of(SMS, NotificationStatus.sent) is NotificationReach.unconfirmed


def test_a_row_still_with_the_worker_is_unknown() -> None:
    assert (
        reach_of(SMS, NotificationStatus.queued) is NotificationReach.unconfirmed
    )


def test_a_carrier_rejection_means_nobody_was_told() -> None:
    assert (
        reach_of(SMS, NotificationStatus.failed) is NotificationReach.not_reached
    )


def test_the_logger_backstop_delivers_to_nobody() -> None:
    # The case that made this module necessary. ``_user_prefs`` appends
    # ``logger`` to every preference list and ``LoggerNotifier`` never
    # fails, so a customer with no reachable channel accumulates a ledger
    # full of 'delivered' rows — and used to be flagged for ignoring
    # prompts that were never sent anywhere.
    assert (
        reach_of(NotificationChannel.logger, NotificationStatus.delivered)
        is NotificationReach.not_reached
    )


@pytest.mark.parametrize(
    "channel", [NotificationChannel.email, NotificationChannel.websocket]
)
def test_delivered_means_delivered_on_every_channel(
    channel: NotificationChannel,
) -> None:
    """Acceptance-without-arrival is a *status* here, not a channel trait.

    There is deliberately no table saying "email really only means the
    relay took it" — the notifier that knows says so at the source by
    returning ``accepted``, which the ledger records as ``sent``. A row
    that does read ``delivered`` therefore means a person's device took
    it, whichever channel carried it, and the reader needs no
    per-channel exceptions kept in sync by hand.
    """
    assert (
        reach_of(channel, NotificationStatus.delivered)
        is NotificationReach.confirmed
    )


@pytest.mark.parametrize(
    "channel", [NotificationChannel.email, NotificationChannel.websocket]
)
def test_a_handover_nobody_confirmed_is_recorded_as_pending(
    channel: NotificationChannel,
) -> None:
    """Where the acceptance-only cases actually land now.

    An SMTP relay taking a message, and a websocket publish whose
    audience is unknowable behind Redis, are both ``sent``: an open
    question that ages into ``not_reached`` rather than a delivery that
    never happened.
    """
    assert (
        reach_of(channel, NotificationStatus.sent)
        is NotificationReach.unconfirmed
    )
    assert (
        reach_of(
            channel,
            NotificationStatus.sent,
            age_seconds=301.0,
            resolution_grace_seconds=300.0,
        )
        is NotificationReach.not_reached
    )


def test_an_unreadable_row_is_unknown_not_an_excuse() -> None:
    # ``not_reached`` is what buys a customer leniency, so it must take
    # evidence. A row this build cannot parse is not evidence.
    assert reach_of(None, None) is NotificationReach.unconfirmed
    assert reach_of(SMS, None) is NotificationReach.unconfirmed


# --- ignorance is not proof, but it expires ------------------------------


GRACE = 300.0


@pytest.mark.parametrize(
    "status", [NotificationStatus.sent, NotificationStatus.queued]
)
def test_a_fresh_pending_row_is_still_an_open_question(
    status: NotificationStatus,
) -> None:
    assert (
        reach_of(SMS, status, age_seconds=5.0, resolution_grace_seconds=GRACE)
        is NotificationReach.unconfirmed
    )


@pytest.mark.parametrize(
    "status", [NotificationStatus.sent, NotificationStatus.queued]
)
def test_a_pending_row_nobody_ever_answered_stops_being_an_open_question(
    status: NotificationStatus,
) -> None:
    """The gap where "we do not know yet" quietly became "we never will".

    A receipt that has not arrived in five minutes is not late, it is
    absent — a callback URL that never resolved, or a worker that died
    holding the job. Left as ``unconfirmed`` forever, one misconfigured
    webhook silently restores the old unfairness for every customer.
    """
    assert (
        reach_of(
            SMS, status, age_seconds=GRACE + 1, resolution_grace_seconds=GRACE
        )
        is NotificationReach.not_reached
    )


def test_ageing_never_touches_a_settled_row() -> None:
    old = {"age_seconds": 86_400.0, "resolution_grace_seconds": GRACE}
    assert (
        reach_of(SMS, NotificationStatus.delivered, **old)
        is NotificationReach.confirmed
    )
    assert (
        reach_of(SMS, NotificationStatus.failed, **old)
        is NotificationReach.not_reached
    )


def test_a_caller_with_no_clock_gets_the_conservative_reading() -> None:
    # Both arguments are needed for ageing to apply, so a caller that
    # cannot measure age keeps the pre-existing "pending is unknown".
    assert reach_of(SMS, NotificationStatus.sent) is NotificationReach.unconfirmed
    assert (
        reach_of(SMS, NotificationStatus.sent, age_seconds=86_400.0)
        is NotificationReach.unconfirmed
    )
    assert (
        reach_of(
            SMS,
            NotificationStatus.sent,
            age_seconds=None,
            resolution_grace_seconds=GRACE,
        )
        is NotificationReach.unconfirmed
    )
