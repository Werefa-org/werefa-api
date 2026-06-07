"""Pure rules for *which* alert to fire (FR-07).

These functions take primitives only — no DB, no HTTP, no notifier. The
application service composes them with persistence + dispatch. Keeping
the decisions inside a free function makes "exactly one head_to_counter
and one you_are_next" trivial to assert with frozen positions.
"""

from dataclasses import dataclass

from werefa.shared.enums import NotificationKind


@dataclass(frozen=True)
class AlertDecision:
    kind: NotificationKind
    body: str


def decide_alert(
    *,
    position: int,
    last_alert_position: int | None,
    top_k: int,
    has_serving_ahead: bool = False,
) -> AlertDecision | None:
    """Return the alert to send for a ticket whose **current** position is
    ``position``, or ``None`` when nothing should fire.

    Two trigger positions matter:

    * ``position == 1`` → ``you_are_next``
    * ``position == top_k`` → ``head_to_counter`` (only when ``top_k > 1``;
      otherwise the two collapse and we prefer ``you_are_next``).
    * ``position == 2`` with someone already ``serving`` → ``head_to_counter``
      (“get ready” pre-alert for the customer behind the counter).

    The ``last_alert_position`` guard is the only thing keeping this from
    re-firing on every queue mutation: we never send the same alert twice
    for the same ticket-position pair.
    """
    if position < 1:
        return None
    if position == 1:
        if last_alert_position == 1:
            return None
        return AlertDecision(
            kind=NotificationKind.you_are_next,
            body="You're next — please head to the counter now.",
        )
    if has_serving_ahead and position == 2:
        if last_alert_position == 2:
            return None
        return AlertDecision(
            kind=NotificationKind.head_to_counter,
            body="Get ready — you're next in line soon!",
        )
    if top_k > 1 and position == top_k:
        if last_alert_position == top_k:
            return None
        return AlertDecision(
            kind=NotificationKind.head_to_counter,
            body=(
                f"You're {top_k} away — start heading to the counter so you "
                "don't lose your spot."
            ),
        )
    return None
