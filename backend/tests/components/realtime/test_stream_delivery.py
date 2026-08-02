"""What the WebSocket stream loop does when both of its legs are ready.

``_stream_service_messages`` waits on two things at once: the next inbound
frame from the client, and the next event from this line's hub queue. The
interesting case is not either leg alone — it is both completing in the
same wake-up, which is common the moment a line is busy, because a client
ping or an app-level ack lands alongside a Call Next event.

These tests drive the loop against a fake socket so that overlap can be
arranged deliberately instead of waited for.
"""

import asyncio
import json
import uuid
from typing import Any

import pytest
from starlette.websockets import WebSocketState

from werefa.realtime import lifespan
from werefa.realtime.infrastructure.coordinator import RealtimeCoordinator
from werefa.realtime.infrastructure.hub import InMemoryQueueHub
from werefa.realtime.interface.router import _stream_service_messages

#: Long enough for the stream task to subscribe and park in ``asyncio.wait``,
#: short enough to keep the suite quick. Nothing here depends on wall clock
#: beyond "the other task got a chance to run".
YIELD_SECONDS = 0.05


class _FakeSocket:
    """Minimal stand-in for a Starlette ``WebSocket``."""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[str] = []
        self.client_state = WebSocketState.CONNECTED

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.client_state = WebSocketState.DISCONNECTED


def _queue_event(reason: str) -> str:
    return json.dumps({"v": 1, "type": "queue_updated", "reason": reason})


async def _run_stream_scenario(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[str],
    client_frames: int,
) -> list[str]:
    """Park the stream, then make both legs ready before it wakes.

    The publishes and the inbound frames are pushed without an intervening
    ``await`` that would let the stream task run, so it comes out of
    ``asyncio.wait`` with both legs already complete — the exact overlap
    that used to cost a subscriber its event.
    """
    hub = InMemoryQueueHub()
    coordinator = RealtimeCoordinator(hub=hub)
    monkeypatch.setattr(lifespan, "coordinator", coordinator)

    service_item_id = uuid.uuid4()
    socket = _FakeSocket()

    stream = asyncio.create_task(
        _stream_service_messages(
            socket,  # type: ignore[arg-type]
            service_item_id,
            message_filter=lambda _message: True,
        )
    )
    await asyncio.sleep(YIELD_SECONDS)  # let it subscribe and park

    for event in events:
        await hub.local_publish(service_item_id, event)
    for index in range(client_frames):
        socket.inbound.put_nowait(
            {"type": "websocket.receive", "text": f"ping-{index}"}
        )

    await asyncio.sleep(YIELD_SECONDS)
    socket.inbound.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(stream, timeout=5.0)
    return socket.sent


def test_queue_event_survives_a_client_frame_in_the_same_wakeup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression: a coinciding client frame must not eat the event.

    The old loop rebuilt both waits every iteration and branched on the
    socket leg first. When both legs completed together it took that
    branch, ``continue``d, and dropped the already-dequeued message on the
    floor — the value had left the queue and was never sent, so the board
    silently missed one Call Next. Nothing logged, nothing raised.
    """
    sent = asyncio.run(
        _run_stream_scenario(
            monkeypatch,
            events=[_queue_event("call_next")],
            client_frames=1,
        )
    )

    assert sent == [_queue_event("call_next")], (
        "the queue event was dropped because a client frame completed in "
        "the same wake-up"
    )


def test_no_event_is_lost_when_a_burst_races_client_traffic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several staff acting at once, with a chatty client alongside.

    This is the "worse under load" report in miniature: the more events and
    frames overlap, the more chances the loop had to take the socket branch
    while an event sat unread.
    """
    events = [_queue_event(f"call_next_{i}") for i in range(25)]

    sent = asyncio.run(
        _run_stream_scenario(monkeypatch, events=events, client_frames=25)
    )

    assert sent == events, (
        f"expected all {len(events)} events in order, got {len(sent)}"
    )


def test_client_frames_alone_send_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inbound chatter is consumed, not echoed."""
    sent = asyncio.run(
        _run_stream_scenario(monkeypatch, events=[], client_frames=5)
    )

    assert sent == []


def test_filtered_events_are_dropped_without_stalling_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticket socket rejects other tickets' events and keeps serving its own.

    Re-arming the queue wait has to happen for filtered messages too, or the
    first irrelevant event would wedge the subscriber permanently.
    """

    async def scenario() -> list[str]:
        hub = InMemoryQueueHub()
        coordinator = RealtimeCoordinator(hub=hub)
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        service_item_id = uuid.uuid4()
        socket = _FakeSocket()

        stream = asyncio.create_task(
            _stream_service_messages(
                socket,  # type: ignore[arg-type]
                service_item_id,
                message_filter=lambda message: "keep" in message,
            )
        )
        await asyncio.sleep(YIELD_SECONDS)
        for reason in ("drop-1", "drop-2", "keep-me", "drop-3", "keep-too"):
            await hub.local_publish(service_item_id, _queue_event(reason))
        await asyncio.sleep(YIELD_SECONDS)
        socket.inbound.put_nowait({"type": "websocket.disconnect"})
        await asyncio.wait_for(stream, timeout=5.0)
        return socket.sent

    sent = asyncio.run(scenario())

    assert sent == [_queue_event("keep-me"), _queue_event("keep-too")]
