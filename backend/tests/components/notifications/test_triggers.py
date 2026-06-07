"""Pure-rule tests for the smart-alert decision tree (FR-07)."""

from werefa.notifications.domain.triggers import decide_alert
from werefa.shared.enums import NotificationKind


def test_decide_alert_at_top_k_emits_head_to_counter() -> None:
    decision = decide_alert(position=3, last_alert_position=None, top_k=3)
    assert decision is not None
    assert decision.kind == NotificationKind.head_to_counter
    assert "3" in decision.body


def test_decide_alert_at_one_emits_you_are_next() -> None:
    decision = decide_alert(position=1, last_alert_position=None, top_k=3)
    assert decision is not None
    assert decision.kind == NotificationKind.you_are_next


def test_decide_alert_position_two_with_serving_emits_get_ready() -> None:
    decision = decide_alert(
        position=2,
        last_alert_position=None,
        top_k=3,
        has_serving_ahead=True,
    )
    assert decision is not None
    assert decision.kind == NotificationKind.head_to_counter
    assert "Get ready" in decision.body


def test_decide_alert_in_between_does_nothing() -> None:
    assert decide_alert(position=2, last_alert_position=None, top_k=3) is None
    assert decide_alert(position=4, last_alert_position=None, top_k=3) is None
    assert decide_alert(position=10, last_alert_position=None, top_k=3) is None


def test_decide_alert_does_not_repeat_at_same_position() -> None:
    assert decide_alert(position=3, last_alert_position=3, top_k=3) is None
    assert decide_alert(position=1, last_alert_position=1, top_k=3) is None


def test_decide_alert_after_top_k_still_fires_you_are_next() -> None:
    # Customer was at K=3 (alerted) and is now at 1 — the second alert
    # *must* still fire because last_alert_position (3) != current (1).
    decision = decide_alert(position=1, last_alert_position=3, top_k=3)
    assert decision is not None
    assert decision.kind == NotificationKind.you_are_next


def test_decide_alert_with_top_k_one_collapses_to_you_are_next() -> None:
    # When the operator configures K=1 the two triggers overlap; we
    # prefer the more urgent message and emit it once.
    assert (
        decide_alert(position=1, last_alert_position=None, top_k=1)
        is not None
    )
    assert (
        decide_alert(position=1, last_alert_position=None, top_k=1).kind
        == NotificationKind.you_are_next
    )


def test_decide_alert_zero_position_is_a_no_op() -> None:
    # Defensive: a buggy position computation should never crash the
    # dispatcher with a negative-or-zero index.
    assert decide_alert(position=0, last_alert_position=None, top_k=3) is None
    assert decide_alert(position=-1, last_alert_position=None, top_k=3) is None
