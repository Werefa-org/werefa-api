"""Pure-rule tests for review eligibility (FR-11, UC-08).

These tests run without a DB or HTTP layer so the contract is fully visible.
"""

import uuid

import pytest

from werefa.reviews.domain.review_rules import (
    ReviewRuleError,
    validate_ticket_can_be_reviewed,
)
from werefa.shared.enums import TicketStatus


def _ok(**overrides):
    base = {
        "ticket_user_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "ticket_status": TicketStatus.completed.value,
        "actor_user_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "has_existing_review": False,
    }
    base.update(overrides)
    return base


def test_completed_ticket_owned_by_actor_no_existing_review_passes() -> None:
    validate_ticket_can_be_reviewed(**_ok())


def test_walk_in_ticket_cannot_be_reviewed() -> None:
    with pytest.raises(ReviewRuleError, match="Walk-in tickets"):
        validate_ticket_can_be_reviewed(**_ok(ticket_user_id=None))


def test_other_user_ticket_cannot_be_reviewed() -> None:
    with pytest.raises(ReviewRuleError, match="your own tickets"):
        validate_ticket_can_be_reviewed(
            **_ok(actor_user_id=uuid.UUID("22222222-2222-2222-2222-222222222222"))
        )


@pytest.mark.parametrize(
    "status",
    [
        TicketStatus.waiting.value,
        TicketStatus.serving.value,
        TicketStatus.no_show.value,
        TicketStatus.cancelled.value,
    ],
)
def test_non_completed_ticket_cannot_be_reviewed(status: str) -> None:
    with pytest.raises(ReviewRuleError, match="Only completed tickets"):
        validate_ticket_can_be_reviewed(**_ok(ticket_status=status))


def test_duplicate_review_rejected() -> None:
    with pytest.raises(ReviewRuleError, match="already been reviewed"):
        validate_ticket_can_be_reviewed(**_ok(has_existing_review=True))
