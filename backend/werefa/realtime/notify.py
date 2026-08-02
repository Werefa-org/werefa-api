import asyncio
import concurrent.futures
import logging
import uuid
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from werefa.realtime.domain.events import (
    BroadcastEventV1,
    LineChatEventV1,
    QueueEventV1,
)
from werefa.shared.models import QueueEntry, utcnow

logger = logging.getLogger(__name__)

#: How long a *confirmed* publish may block the calling thread. The publish
#: is an in-memory hub put without Redis and one round trip with it, so this
#: is a stall ceiling for a wedged broker, not an expected wait.
PUBLISH_CONFIRM_TIMEOUT_SECONDS = 2.0


def _ticket_position(session: Session, ticket: QueueEntry) -> int | None:
    """Display depth for realtime payloads: "you are #N in line".

    Same ``(priority desc, joined_at)`` ordering the counter calls in, via
    :mod:`werefa.queue.application.line_order`. It used to count ticket
    numbers, which quietly disagreed with both the queue snapshot and the
    call order as soon as a VIP joined — so a client that trusted the
    stream showed a different position from the one it fetched.
    """
    from werefa.queue.application import line_order

    if ticket.status not in line_order.ACTIVE_STATUSES:
        return None
    count = line_order.line_position(session, ticket)
    if count < 1:
        return None
    return count


def _log_fanout_result(what: str, fut: Any) -> None:
    try:
        fut.result()
    except (asyncio.CancelledError, concurrent.futures.CancelledError):
        return
    except Exception:
        logger.exception("%s fan-out failed", what)


def _schedule_publish(service_item_id: uuid.UUID, text: str, *, what: str) -> None:
    """Hand one fan-out to the app event loop, from whichever thread we're on.

    Nearly every caller is a sync ``def`` route, so it runs in Starlette's
    worker threadpool rather than on the loop. ``loop.create_task`` is
    **not thread-safe**: called from a foreign thread it appends the task
    to the loop's ready queue *without* waking the loop. An idle loop —
    which is the normal state of a queue backend between requests — then
    sits in ``epoll`` until some unrelated event happens to wake it, and
    only then runs the publish. That is the "board didn't update after
    Call Next" and "the customer app missed the event entirely" report:
    the event was never dropped, it was stalled for an unbounded time.

    ``run_coroutine_threadsafe`` routes through ``call_soon_threadsafe``,
    which writes the loop's self-pipe and wakes it immediately. The one
    caller already on the loop (the async join-with-files route) still
    goes through ``create_task``, which is correct and cheaper there.
    """
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or loop.is_closed() or not loop.is_running():
        return

    # The count a publish reports back is what ``publish_and_confirm``
    # needs; this caller is fire-and-forget and discards it.
    coro: Coroutine[Any, Any, int | None] = c.publish(service_item_id, text)

    try:
        running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is loop:
        task = loop.create_task(coro)
        task.add_done_callback(lambda f: _log_fanout_result(what, f))
        return

    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        # Loop closed between the check above and here (shutdown race).
        coro.close()
        logger.warning("%s dropped: event loop no longer accepting work", what)
        return
    future.add_done_callback(lambda f: _log_fanout_result(what, f))


@dataclass(frozen=True)
class PublishOutcome:
    """What a confirmed publish achieved — and for whom.

    ``published`` alone is what this used to return, and it turned out to
    answer the wrong question. A publish to a service line nobody is
    watching succeeds completely and delivers to nobody, so the
    notification dispatcher read "the fan-out happened" as "the customer
    was told", stopped walking their preference list, and never sent the
    SMS that would have reached them.

    ``recipients`` is therefore the number of subscriber queues that took
    the message, with ``None`` meaning "cannot know": behind Redis the
    subscribers are on other replicas and no count comes back. ``None``
    and ``0`` must not be collapsed — one is ignorance, the other is a
    definite answer that nobody heard it.
    """

    published: bool
    recipients: int | None = None

    def __bool__(self) -> bool:
        # Keeps ``if publish_and_confirm(...)`` reading as it always did.
        return self.published

    @property
    def reached_nobody(self) -> bool:
        """Provably delivered to zero subscribers."""
        return self.published and self.recipients == 0

    @property
    def audience_unknown(self) -> bool:
        return self.published and self.recipients is None


NOT_PUBLISHED = PublishOutcome(published=False)


def publish_and_confirm(
    service_item_id: uuid.UUID,
    text: str,
    *,
    what: str,
    timeout_seconds: float = PUBLISH_CONFIRM_TIMEOUT_SECONDS,
) -> PublishOutcome:
    """Publish, and report whether the fan-out actually happened.

    :func:`_schedule_publish` is fire-and-forget, which is right for the
    queue fan-out: nothing downstream depends on its result. It is *wrong*
    for the websocket notifier, whose return value the dispatcher reads as
    "delivered" — a truthy answer stops it trying SMS and email and writes
    ``delivered`` to the ledger. Scheduling successfully is not delivering,
    so that caller needs the outcome, not the hand-off.

    Off the loop we wait, briefly and with a bound, for the publish to
    complete. A timeout is reported as *not* delivered so the dispatcher
    falls through to a channel that can still reach the customer; the task
    is cancelled to avoid a late duplicate, but a websocket toast arriving
    alongside an SMS is a far better failure than silence.

    On the loop we cannot wait at all — blocking would deadlock the very
    loop that has to produce the result — so we do not schedule and hope.
    Either the publish completes synchronously right here, which it can
    whenever there is no Redis hop, or we report undelivered. Scheduling a
    task and returning ``True`` would be the same false-delivered bug this
    function exists to remove, reached by a different route.
    """
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or loop.is_closed() or not loop.is_running():
        return NOT_PUBLISHED

    try:
        running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is loop:
        # No coroutine is created on this path: an unawaited one would warn,
        # and a scheduled one would be a delivery we cannot vouch for.
        reached = c.try_publish_now(service_item_id, text)
        if reached is not None:
            # ``0`` is a completed publish that reached nobody, which is a
            # result and not a failure — hence ``is not None`` rather than
            # a truthiness check.
            return PublishOutcome(published=True, recipients=reached)
        logger.info(
            "%s not confirmable on the event loop thread; reporting as "
            "undelivered so the caller can use another channel",
            what,
        )
        return NOT_PUBLISHED

    coro: Coroutine[Any, Any, int | None] = c.publish(service_item_id, text)
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        coro.close()
        return NOT_PUBLISHED

    try:
        reached = future.result(timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        logger.warning(
            "%s did not complete within %ss; reporting as undelivered",
            what,
            timeout_seconds,
        )
        return NOT_PUBLISHED
    except Exception:
        logger.exception("%s fan-out failed", what)
        return NOT_PUBLISHED
    return PublishOutcome(published=True, recipients=reached)


def notify_queue_subscribers(
    session: Session,
    service_item_id: uuid.UUID,
    *,
    ticket: QueueEntry | None = None,
    reason: str | None = None,
) -> None:
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    text = QueueEventV1.build(
        service_item_id,
        ticket_id=ticket.id if ticket else None,
        status=ticket.status if ticket else None,
        position=_ticket_position(session, ticket) if ticket else None,
        reason=reason,
    ).model_dump_json()
    _schedule_publish(service_item_id, text, what="Queue event")


def notify_broadcast_subscribers(
    *,
    broadcast_id: uuid.UUID,
    provider_id: uuid.UUID,
    body_text: str,
    severity: str,
    author_role: str = "staff",
    author_label: str = "Business",
    service_item_ids: Iterable[uuid.UUID],
    original_service_item_id: uuid.UUID | None,
) -> None:
    """Best-effort fan-out of a broadcast to one or more service-line channels.

    Failures are logged but never raise — the broadcast row is already
    persisted and reachable through the REST list endpoint.
    """
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    occurred_at = utcnow()
    for sid in service_item_ids:
        role: str = author_role if author_role in ("owner", "staff") else "staff"
        event = BroadcastEventV1(
            broadcast_id=broadcast_id,
            provider_id=provider_id,
            # Wire-level: name the *channel* this delivery uses so clients
            # always have a concrete service line to filter on. The
            # persisted record keeps `original_service_item_id` truthful.
            service_item_id=sid if original_service_item_id is not None else sid,
            body=body_text,
            severity=_severity_literal(severity),
            author_role=role,  # type: ignore[arg-type]
            author_label=author_label,
            occurred_at=occurred_at,
        )
        text = event.model_dump_json()
        _schedule_publish(sid, text, what="Broadcast")


def notify_line_chat_subscribers(
    *,
    message_id: uuid.UUID,
    service_item_id: uuid.UUID,
    body_text: str,
    author_role: str,
    author_label: str,
    author_user_id: uuid.UUID,
) -> None:
    from werefa.realtime import lifespan

    c = lifespan.coordinator
    loop = lifespan.main_event_loop
    if c is None or loop is None or not loop.is_running():
        return

    occurred_at = utcnow()
    event = LineChatEventV1(
        message_id=message_id,
        service_item_id=service_item_id,
        author_user_id=author_user_id,
        body=body_text,
        author_role=author_role[:32],
        author_label=author_label[:200],
        occurred_at=occurred_at,
    )
    text = event.model_dump_json()
    _schedule_publish(service_item_id, text, what="Line chat")


def _severity_literal(value: str) -> str:
    """Narrow ``str`` to the BroadcastEventV1 Literal at the boundary.

    The pydantic Literal validation will reject anything else, but we
    fall back to ``info`` to keep the realtime layer permissive when
    fed unexpected input from upstream changes.
    """
    if value in ("info", "warning", "critical"):
        return value
    return "info"
