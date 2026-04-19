import pytest

from werefa.components.queue.domain.ticket_rules import (
    is_terminal_status,
    validate_manual_status_change,
)
from werefa.enums import TicketStatus


def test_validate_completed_only_from_serving() -> None:
    validate_manual_status_change(TicketStatus.serving.value, TicketStatus.completed)

    with pytest.raises(ValueError, match="Only serving"):
        validate_manual_status_change(
            TicketStatus.waiting.value, TicketStatus.completed
        )


def test_validate_terminal_blocked() -> None:
    with pytest.raises(ValueError, match="terminal"):
        validate_manual_status_change(
            TicketStatus.completed.value, TicketStatus.no_show
        )


def test_no_show_from_waiting() -> None:
    validate_manual_status_change(TicketStatus.waiting.value, TicketStatus.no_show)


def test_is_terminal() -> None:
    assert is_terminal_status("completed") is True
    assert is_terminal_status("waiting") is False
