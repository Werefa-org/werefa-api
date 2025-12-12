from werefa.shared.enums import TicketStatus


def active_status_values() -> tuple[str, ...]:
    return (TicketStatus.waiting.value, TicketStatus.serving.value)


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

    if new_status in (TicketStatus.no_show, TicketStatus.cancelled):
        return

    raise ValueError("Use call-next or join flows for other transitions")
