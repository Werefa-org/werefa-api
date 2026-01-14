"""Pure rules for whether a review is allowed.

Kept free of `Session` and HTTP concerns so they're trivially unit-testable.
"""

import uuid

from werefa.shared.enums import TicketStatus


class ReviewRuleError(ValueError):
    """Raised when a review is not allowed for a given ticket / actor."""


def validate_ticket_can_be_reviewed(
    *,
    ticket_user_id: uuid.UUID | None,
    ticket_status: str,
    actor_user_id: uuid.UUID,
    has_existing_review: bool,
) -> None:
    """Enforce FR-11 / UC-08 review eligibility rules.

    Raises:
        ReviewRuleError: with a message safe to surface as the API ``detail``.
    """
    if ticket_user_id is None:
        raise ReviewRuleError("Walk-in tickets cannot be reviewed")
    if ticket_user_id != actor_user_id:
        raise ReviewRuleError("You can only review your own tickets")
    if ticket_status != TicketStatus.completed.value:
        raise ReviewRuleError("Only completed tickets can be reviewed")
    if has_existing_review:
        raise ReviewRuleError("This ticket has already been reviewed")
