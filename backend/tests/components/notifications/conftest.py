"""Shared harness for tests that care about a delivery's *outcome*.

Channels that leave the machine (SMS, email) are handed to the delivery
worker rather than sent inside ``dispatch``, so an assertion like "the
gateway was called and the ledger says delivered" is no longer true by
the time ``dispatch`` returns.

``inline_delivery`` collapses that back into one synchronous call: the
real :func:`~werefa.notifications.application.service.deliver_job` runs
on the calling thread against stub sessions. The hand-off *itself* — that
dispatch defers, and waits for the transaction — is what
``test_deferred_dispatch.py`` covers; tests using this fixture are
deliberately not re-testing it.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest

from werefa.core.config import settings
from werefa.notifications.application import service as notifications_service
from werefa.notifications.domain.retry import RetryPolicy
from werefa.notifications.infrastructure.delivery import InlineDeliveryQueue
from werefa.shared.models import Notification, User

# Retries are exercised properly in ``test_retry_policy`` and
# ``test_delivery_queue``; here they only need to not cost wall-clock.
_NO_WAIT = RetryPolicy(max_attempts=3, base_seconds=0.0001, max_seconds=0.001, jitter_ratio=0.0)


@dataclass
class _StandInUser:
    """Fallback recipient for tests that don't care who they notified.

    ``deliver_job`` re-loads the user by id in its own session, and these
    tests hand ``dispatch`` a hand-rolled user that was never in the
    database. A test whose assertions depend on the recipient's own
    fields (a phone number, an address) must register it with
    :meth:`InlineDelivery.recipient` instead of relying on this.
    """

    id: uuid.UUID
    is_active: bool = True
    email: str | None = "customer@example.com"


@dataclass
class _StubWorkerSession:
    """What ``deliver_job`` opens for itself."""

    persisted: list[Any]
    users: dict[uuid.UUID, Any]

    def __enter__(self) -> _StubWorkerSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def get(self, model: type, pk: uuid.UUID) -> Any:
        if model is User:
            return self.users.get(pk) or _StandInUser(id=pk)
        return next((r for r in self.persisted if getattr(r, "id", None) == pk), None)

    def add(self, _obj: Any) -> None:
        return None

    def commit(self) -> None:
        return None


@dataclass
class InlineDelivery:
    """Handle for tests: hands out the dispatch session the worker reads."""

    persisted: list[Any] = field(default_factory=list)
    users: dict[uuid.UUID, Any] = field(default_factory=dict)

    def session(self) -> _DispatchSession:
        return _DispatchSession(self.persisted)

    def recipient(self, user: Any) -> Any:
        """Make ``user`` findable by the worker, and hand it back.

        Needed whenever an assertion depends on the recipient's own
        fields — the worker looks the user up again rather than trusting
        whatever object ``dispatch`` was handed.
        """
        self.users[user.id] = user
        return user

    @property
    def rows(self) -> list[Notification]:
        return [r for r in self.persisted if isinstance(r, Notification)]


@dataclass
class _DispatchSession:
    """Stands in for the request's session.

    No ``.info``, which is the documented signal for "no transaction to
    wait on" — that is what makes the hand-off happen immediately here.
    """

    persisted: list[Any]

    def add(self, obj: Any) -> None:
        self.persisted.append(obj)

    def flush(self) -> None:
        return None

    def refresh(self, _obj: Any) -> None:
        return None


@pytest.fixture
def inline_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[InlineDelivery, None, None]:
    handle = InlineDelivery()
    # Pinned rather than inherited: this fixture exists to exercise the
    # deferred path, so a deployment running with the rollback lever off
    # must not quietly turn these into tests of the old behaviour.
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", True)
    notifications_service.set_delivery_queue(
        InlineDeliveryQueue(  # type: ignore[arg-type]
            notifications_service.deliver_job,
            policy=_NO_WAIT,
            sleeper=lambda _: None,
        )
    )
    notifications_service.set_delivery_session_factory(
        lambda: _StubWorkerSession(handle.persisted, handle.users)  # type: ignore[arg-type,return-value]
    )
    yield handle
    notifications_service.set_delivery_queue(None)
    notifications_service.set_delivery_session_factory(None)
