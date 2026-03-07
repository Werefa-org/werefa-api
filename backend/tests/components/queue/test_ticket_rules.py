from datetime import datetime, timedelta, timezone

import pytest

from werefa.queue.domain.ticket_rules import (
    assert_recall_completed_allowed,
    is_terminal_status,
    validate_manual_status_change,
)
from werefa.shared.enums import TicketStatus


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


def test_validate_no_show_only_from_serving() -> None:
    validate_manual_status_change(TicketStatus.serving.value, TicketStatus.no_show)

    with pytest.raises(ValueError, match="Only serving"):
        validate_manual_status_change(TicketStatus.waiting.value, TicketStatus.no_show)


def test_is_terminal() -> None:
    assert is_terminal_status("completed") is True
    assert is_terminal_status("waiting") is False


def test_assert_recall_completed_allowed() -> None:
    completed = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert_recall_completed_allowed(
        completed_at=completed,
        now=completed + timedelta(seconds=10),
        window_seconds=90,
    )

    with pytest.raises(ValueError, match="Recall is only allowed"):
        assert_recall_completed_allowed(
            completed_at=completed,
            now=completed + timedelta(seconds=100),
            window_seconds=90,
        )

    with pytest.raises(ValueError, match="completion timestamp"):
        assert_recall_completed_allowed(
            completed_at=None,
            now=completed,
            window_seconds=90,
        )
