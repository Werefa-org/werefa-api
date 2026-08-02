"""``WebSocketNotifier.send`` must only claim delivery it actually made.

This notifier's return value is load-bearing in a way the queue fan-out's
is not. ``dispatch`` reads ``True`` as *delivered*: it stops walking the
user's channel preferences and writes ``delivered`` to the ledger, so SMS
and email are never attempted. A notifier that reports success for a
publish which merely got scheduled therefore costs the customer every
channel at once — the alert is recorded as sent and arrives nowhere.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator

import pytest

from tests.utils.realtime import (
    DELIVERY_TIMEOUT_SECONDS,
    HangingCoordinator,
    RecordingCoordinator,
    idle_event_loop,
)
from werefa.notifications.notifier import (
    DeliveryOutcome,
    NotificationPayload,
    WebSocketNotifier,
)
from werefa.realtime import lifespan
from werefa.realtime.infrastructure.coordinator import RealtimeCoordinator
from werefa.realtime.infrastructure.hub import InMemoryQueueHub
from werefa.realtime.notify import publish_and_confirm
from werefa.shared.enums import NotificationKind
from werefa.shared.models import User

#: Every assertion about delivery must run *inside* the live-loop fixture.
#: Tearing the loop down calls ``call_soon_threadsafe(loop.stop)``, which
#: wakes it — and a woken loop flushes exactly the stranded task this module
#: exists to catch, so an assertion made after teardown passes against the
#: broken code. That is the same "unrelated traffic wakes the loop" effect
#: that made the production bug intermittent.
#:
#: ``NotificationPayload`` is a frozen dataclass, so an absent ticket has to
#: be built in rather than assigned after the fact.
_UNSET: uuid.UUID = uuid.UUID(int=0)


def _payload(*, ticket_id: uuid.UUID | None = _UNSET) -> NotificationPayload:
    return NotificationPayload(
        kind=NotificationKind.you_are_next,
        body="You're next — please come to the counter.",
        ticket_id=uuid.uuid4() if ticket_id is _UNSET else ticket_id,
        service_item_id=uuid.uuid4(),
        position=1,
    )


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="customer@example.com",
        hashed_password="x",
        is_active=True,
    )


@pytest.fixture
def live_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[RecordingCoordinator]:
    """An idle loop wired into ``lifespan``, alive for the whole test body."""
    coordinator = RecordingCoordinator()
    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        yield coordinator


def test_alert_from_a_worker_thread_reaches_an_idle_loop(
    live_loop: RecordingCoordinator,
) -> None:
    """The regression: scheduling is not delivering.

    Every sync ``def`` route that reaches dispatch runs on a worker thread.
    The old ``loop.create_task`` here appended the publish to the loop's
    ready queue without waking the loop, then returned ``True`` — so the
    "you're next" alert was booked as delivered, the SMS fallback was
    suppressed, and the loop went on sleeping. The ``except RuntimeError``
    guarding it never fired, because from a foreign thread ``create_task``
    does not raise: it succeeds and does nothing.

    Asserting the return value alone would still pass against that code, so
    the publish itself is what this checks.
    """
    coordinator = live_loop
    payload = _payload()

    delivered = WebSocketNotifier().send(user=_user(), payload=payload)

    assert delivered is True
    assert coordinator.arrived.wait(DELIVERY_TIMEOUT_SECONDS), (
        "send() reported delivered but the publish never ran: the loop was "
        "never woken"
    )
    assert len(coordinator.published) == 1
    published_id, text = coordinator.published[0]
    assert published_id == payload.service_item_id
    event = json.loads(text)
    assert event["ticket_id"] == str(payload.ticket_id)
    assert event["body"] == payload.body


def test_send_reports_undelivered_when_realtime_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No loop means the dispatcher must fall through to SMS or email."""
    coordinator = RecordingCoordinator()
    monkeypatch.setattr(lifespan, "coordinator", coordinator)
    monkeypatch.setattr(lifespan, "main_event_loop", None)

    assert WebSocketNotifier().send(user=_user(), payload=_payload()) is False
    assert coordinator.published == []


def test_send_reports_undelivered_without_a_ticket_to_target(
    live_loop: RecordingCoordinator,
) -> None:
    """A ``notify_v1`` event addresses exactly one ticket, or it is not one."""
    assert (
        WebSocketNotifier().send(user=_user(), payload=_payload(ticket_id=None))
        is False
    )
    assert live_loop.published == []


def _send_on_loop(
    loop: asyncio.AbstractEventLoop,
    payload: NotificationPayload,
    coordinator: RecordingCoordinator,
) -> tuple[bool, int]:
    """Run ``send`` on the loop thread, as the async join route does.

    Returns what ``send`` claimed *and* how many publishes had actually
    happened at the moment it claimed it, sampled inside the coroutine with
    no await in between. Sampling back on the test thread instead would let
    the loop run a scheduled task first, and a merely-scheduled publish
    would look like a completed one.
    """

    async def _call() -> tuple[bool, int]:
        delivered = WebSocketNotifier().send(user=_user(), payload=payload)
        return delivered, len(coordinator.published)

    return asyncio.run_coroutine_threadsafe(_call(), loop).result(5.0)


def test_send_from_the_loop_thread_publishes_before_claiming_delivery(
    live_loop: RecordingCoordinator,
) -> None:
    """Dispatch reached from the async join route is already on the loop.

    Waiting for a scheduled task there would deadlock the loop that has to
    run it, so this branch must instead *complete* the publish inline. It
    can: without a Redis hop the fan-out is a list snapshot and unbounded
    queue puts, neither of which can suspend.

    The assertion that matters is ordering — the publish must have happened
    by the time ``send`` returns ``True``, not merely be scheduled — so the
    count is sampled at the instant of the claim.
    """
    coordinator = live_loop
    payload = _payload()
    loop = lifespan.main_event_loop
    assert loop is not None

    delivered, published_when_claimed = _send_on_loop(
        loop, payload, coordinator
    )

    assert delivered is True
    assert published_when_claimed == 1, (
        "send() claimed delivered on the loop thread before the publish had "
        "actually run"
    )
    assert coordinator.published[0][0] == payload.service_item_id


def test_send_on_the_loop_reports_undelivered_when_it_cannot_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a Redis hop there is no honest synchronous answer, so: not delivered.

    The publish is a network round trip that genuinely needs the loop we are
    standing on. Rather than schedule it and claim success — the original
    bug, reached by another route — we decline, and the dispatcher reaches
    the customer on a channel whose outcome it can actually confirm.
    """
    coordinator = RecordingCoordinator(can_publish_now=False)
    payload = _payload()

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)

        delivered, _ = _send_on_loop(loop, payload, coordinator)
        assert delivered is False
        # Nothing was scheduled behind our back either: a publish we refused
        # to vouch for must not turn up later as a duplicate alongside the
        # SMS the dispatcher will now send.
        assert not coordinator.arrived.wait(0.25)

    assert coordinator.published == []


def test_a_real_coordinator_delivers_to_a_subscriber_on_the_loop_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end against the real hub, not a stand-in.

    The synchronous path is only sound because ``local_publish_nowait``
    reaches the same subscriber queues ``local_publish`` does. That claim is
    worth checking against the real objects.
    """
    coordinator = RealtimeCoordinator(hub=InMemoryQueueHub())
    payload = _payload()

    async def _subscribe_send_and_read() -> str:
        queue, _unsubscribe = await coordinator.hub.subscribe(
            payload.service_item_id  # type: ignore[arg-type]
        )
        assert WebSocketNotifier().send(user=_user(), payload=payload) is True
        # No await between the send and the read: if the event were merely
        # scheduled rather than published, the queue would still be empty.
        return queue.get_nowait()

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        text = asyncio.run_coroutine_threadsafe(
            _subscribe_send_and_read(), loop
        ).result(5.0)

    assert json.loads(text)["ticket_id"] == str(payload.ticket_id)


def test_a_wedged_publish_is_reported_as_undelivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publish that never completes must not stall the request forever.

    Exercised on ``publish_and_confirm`` directly so the timeout can be set
    small; the notifier passes the module default
    (``PUBLISH_CONFIRM_TIMEOUT_SECONDS``). Reporting ``False`` is what lets
    the dispatcher still reach the customer by SMS.
    """
    coordinator = HangingCoordinator()

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)

        confirmed = publish_and_confirm(
            uuid.uuid4(),
            "{}",
            what="Ticket alert",
            timeout_seconds=0.25,
        )

    assert confirmed.published is False
    assert coordinator.started.is_set(), "the publish never even started"


# --- who actually received it -------------------------------------------
#
# Completing a publish is not the same as arriving, and that gap survived
# the ``create_task`` fix above. A publish to a service line nobody is
# subscribed to completes perfectly and reaches nobody — which, with the
# default preferences (``websocket, email, logger``), is every customer
# whose app is closed. The alert was booked ``delivered``, SMS was never
# tried, and FR-05 liveness then flagged them for not answering it.


def test_a_publish_nobody_is_listening_to_is_not_a_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero subscribers is an answer, not a failure to get one.

    Reporting undelivered is what lets ``dispatch`` fall through to a
    channel that can still reach the customer.
    """
    coordinator = RealtimeCoordinator(hub=InMemoryQueueHub())

    async def _send_with_nobody_subscribed() -> DeliveryOutcome:
        return WebSocketNotifier().deliver(user=_user(), payload=_payload())

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        outcome = asyncio.run_coroutine_threadsafe(
            _send_with_nobody_subscribed(), loop
        ).result(5.0)

    assert outcome is DeliveryOutcome.permanent


def test_a_live_subscriber_is_a_real_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = RealtimeCoordinator(hub=InMemoryQueueHub())
    payload = _payload()

    async def _subscribe_and_send() -> DeliveryOutcome:
        await coordinator.hub.subscribe(payload.service_item_id)  # type: ignore[arg-type]
        return WebSocketNotifier().deliver(user=_user(), payload=payload)

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        outcome = asyncio.run_coroutine_threadsafe(
            _subscribe_and_send(), loop
        ).result(5.0)

    assert outcome is DeliveryOutcome.delivered


def test_an_unknowable_audience_is_neither_claimed_nor_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behind Redis the subscribers may be on another replica.

    Falling through here would double-notify every app user in a
    multi-replica deployment; claiming delivery would be the same lie in
    the other direction. ``accepted`` says the event left and nobody can
    vouch for who received it — and the ledger row ages out of that
    rather than sitting on it forever.
    """
    coordinator = RecordingCoordinator(recipients=None)

    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "coordinator", coordinator)
        monkeypatch.setattr(lifespan, "main_event_loop", loop)
        outcome = WebSocketNotifier().deliver(user=_user(), payload=_payload())

        assert outcome is DeliveryOutcome.accepted
        assert coordinator.published, "the event was never published at all"


def test_zero_and_unknown_are_not_the_same_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distinction the whole change rests on.

    Collapsing them either texts people who are already looking at the
    app, or records an alert as delivered when nothing received it.
    """
    with idle_event_loop() as loop:
        monkeypatch.setattr(lifespan, "main_event_loop", loop)

        monkeypatch.setattr(lifespan, "coordinator", RecordingCoordinator(recipients=0))
        assert (
            WebSocketNotifier().deliver(user=_user(), payload=_payload())
            is DeliveryOutcome.permanent
        )

        monkeypatch.setattr(
            lifespan, "coordinator", RecordingCoordinator(recipients=None)
        )
        assert (
            WebSocketNotifier().deliver(user=_user(), payload=_payload())
            is DeliveryOutcome.accepted
        )
