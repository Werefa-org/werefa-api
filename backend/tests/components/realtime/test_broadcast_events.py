"""Schema and ticket-filter tests for broadcast realtime events.

These run without a DB or HTTP server: they exercise the wire format
(``BroadcastEventV1``) and the ticket-stream filter
(``_message_for_ticket``) directly.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from werefa.realtime.domain.events import (
    BROADCAST_EVENT_TYPE,
    BroadcastEventV1,
    QueueEventV1,
)
from werefa.realtime.interface.router import _message_for_ticket


def _broadcast_payload(
    *,
    severity: str = "info",
    body: str = "Doctor running 20 min late",
    service_item_id: uuid.UUID | None = None,
) -> str:
    event = BroadcastEventV1(
        broadcast_id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        service_item_id=service_item_id,
        body=body,
        severity=severity,  # type: ignore[arg-type]
        occurred_at=datetime(2026, 4, 30, 9, tzinfo=timezone.utc),
    )
    return event.model_dump_json()


def test_broadcast_event_serialises_with_iso_timestamp() -> None:
    payload = _broadcast_payload()
    raw = json.loads(payload)
    assert raw["type"] == BROADCAST_EVENT_TYPE
    assert raw["v"] == 1
    assert raw["severity"] == "info"
    assert "occurred_at" in raw
    # Round-trip: a serialised event should validate again.
    event = BroadcastEventV1.model_validate(raw)
    assert event.body == "Doctor running 20 min late"


def test_broadcast_event_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        BroadcastEventV1(
            broadcast_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            body="x",
            severity="loud",  # type: ignore[arg-type]
            occurred_at=datetime.now(timezone.utc),
        )


def test_broadcast_event_body_length_enforced() -> None:
    with pytest.raises(ValidationError):
        BroadcastEventV1(
            broadcast_id=uuid.uuid4(),
            provider_id=uuid.uuid4(),
            body="x" * 501,
            severity="info",
            occurred_at=datetime.now(timezone.utc),
        )


def test_filter_passes_broadcast_to_any_ticket_socket() -> None:
    payload = _broadcast_payload()
    assert _message_for_ticket(payload, uuid.uuid4()) is True


def test_filter_passes_queue_event_only_for_matching_ticket_id() -> None:
    ticket = uuid.uuid4()
    other = uuid.uuid4()
    event = QueueEventV1.build(
        service_item_id=uuid.uuid4(),
        ticket_id=ticket,
        status="serving",
        position=1,
        reason="call_next",
    )
    payload = event.model_dump_json()

    assert _message_for_ticket(payload, ticket) is True
    assert _message_for_ticket(payload, other) is False


def test_filter_rejects_malformed_json() -> None:
    assert _message_for_ticket("not-json", uuid.uuid4()) is False
    # Top-level array also rejected (filter expects an object).
    assert _message_for_ticket("[1,2]", uuid.uuid4()) is False


def test_filter_rejects_unknown_type() -> None:
    payload = json.dumps(
        {
            "v": 1,
            "type": "made_up_v1",
            "service_item_id": str(uuid.uuid4()),
        }
    )
    assert _message_for_ticket(payload, uuid.uuid4()) is False
