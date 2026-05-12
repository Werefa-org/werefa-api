from datetime import datetime

from werefa.shared.enums import TicketStatus


def active_status_values() -> tuple[str, ...]:
    return (
        TicketStatus.waiting.value,
        TicketStatus.serving.value,
        TicketStatus.pending_approval.value,
    )


def terminal_status_values() -> tuple[str, ...]:
    return (
        TicketStatus.completed.value,
        TicketStatus.no_show.value,
        TicketStatus.cancelled.value,
    )


def is_terminal_status(status: str) -> bool:
    return status in terminal_status_values()


def validate_manual_status_change(
    current_status: str, new_status: TicketStatus
) -> None:
    if is_terminal_status(current_status):
        raise ValueError("Ticket is already in a terminal status")

    if new_status == TicketStatus.completed:
        if current_status != TicketStatus.serving.value:
            raise ValueError("Only serving tickets can be marked completed")
        return

    if new_status == TicketStatus.no_show:
        # US-SP-06 / FR-09: no-show is only meaningful after the customer
        # was called (ticket is ``serving``).
        if current_status != TicketStatus.serving.value:
            raise ValueError("Only serving tickets can be marked no-show")
        return

    if new_status == TicketStatus.cancelled:
        return

    raise ValueError("Use call-next or join flows for other transitions")


def assert_recall_completed_allowed(
    *,
    completed_at: datetime | None,
    now: datetime,
    window_seconds: int,
) -> None:
    """FR-09: recall only applies to a freshly completed ticket."""
    if completed_at is None:
        raise ValueError("Ticket has no completion timestamp")
    if window_seconds < 0:
        raise ValueError("Invalid recall window")
    delta = (now - completed_at).total_seconds()
    if delta < 0:
        raise ValueError("Invalid completion time")
    if delta > window_seconds:
        raise ValueError(
            f"Recall is only allowed within {window_seconds} seconds of completion"
        )
