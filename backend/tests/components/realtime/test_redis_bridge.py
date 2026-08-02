"""Failure behaviour of the cross-worker Redis bridge.

``REALTIME_REDIS_URL`` is unset in dev and in the test environment, so this
path only runs in multi-worker deployments — which is exactly where the
fan-out was reported as least reliable and least observable. The bridge is
driven here with stubs rather than a live Redis.
"""

import asyncio
import uuid

from werefa.realtime.infrastructure.hub import InMemoryQueueHub
from werefa.realtime.infrastructure.redis_bridge import RedisPubSubBackend


class _FailingClient:
    """A Redis client whose publishes always fail."""

    def __init__(self) -> None:
        self.attempts = 0

    async def publish(self, channel: str, message: str) -> None:
        self.attempts += 1
        raise ConnectionError("redis is down")


class _StubPubSub:
    def __init__(self) -> None:
        self.patterns: list[str] = []
        self.closed = False

    async def psubscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    async def close(self) -> None:
        self.closed = True


class _ReconnectingClient:
    def __init__(self) -> None:
        self.pubsubs: list[_StubPubSub] = []

    def pubsub(self, **_kwargs: object) -> _StubPubSub:
        created = _StubPubSub()
        self.pubsubs.append(created)
        return created


def test_a_redis_blip_still_delivers_to_this_worker() -> None:
    """Local subscribers must not pay for a broker outage.

    Publishes go to Redis and come back through the listener, so a failed
    publish used to lose the event for *everyone*, including the sockets
    attached to the very process that produced it. Cross-worker delivery is
    genuinely gone, but this worker degrades to the no-Redis behaviour
    instead of going silent.
    """
    hub = InMemoryQueueHub()
    bridge = RedisPubSubBackend("redis://unused", hub)
    client = _FailingClient()
    bridge._client = client
    service_item_id = uuid.uuid4()

    async def scenario() -> str:
        queue, _unsubscribe = await hub.subscribe(service_item_id)
        await bridge.publish_to_channel(service_item_id, "queue-event")
        return await asyncio.wait_for(queue.get(), timeout=2.0)

    assert asyncio.run(scenario()) == "queue-event"
    assert client.attempts == 1


def test_resubscribe_rebuilds_the_subscription() -> None:
    """One dropped connection must not blind the worker permanently.

    The listen loop caught its exception and span straight back into
    ``get_message`` on a pubsub whose subscription was gone, so every
    subsequent queue event for every line this worker served vanished until
    the process restarted.
    """
    hub = InMemoryQueueHub()
    bridge = RedisPubSubBackend("redis://unused", hub)
    client = _ReconnectingClient()
    bridge._client = client
    stale = _StubPubSub()
    bridge._pub = stale

    asyncio.run(bridge._resubscribe())

    assert stale.closed, "the dead pubsub was left open"
    assert len(client.pubsubs) == 1
    assert client.pubsubs[0].patterns == ["werefa:queue:*"]
    assert bridge._pub is client.pubsubs[0]
