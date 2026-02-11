"""Notification dispatch + ledger + smart-alert orchestration (FR-07)."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.notifications.domain.triggers import decide_alert
from werefa.notifications.notifier import (
    NotificationPayload,
    Notifier,
    default_registry,
)
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    TicketStatus,
)
from werefa.shared.models import (
    Notification,
    NotificationPrefsUpdate,
    QueueEntry,
    User,
)

logger = logging.getLogger(__name__)

# Module-level registry mutable for tests via ``set_registry``. The
# default registry is rebuilt lazily so importing this module from a
# pure-rule test that doesn't need realtime stays cheap.
_registry: dict[NotificationChannel, Notifier] | None = None


def get_registry() -> dict[NotificationChannel, Notifier]:
    global _registry
    if _registry is None:
        _registry = default_registry()
    return _registry


def set_registry(registry: dict[NotificationChannel, Notifier] | None) -> None:
    """Test seam: swap the registry for fakes; pass ``None`` to reset."""
    global _registry
    _registry = registry


def _user_prefs(user: User) -> list[NotificationChannel]:
    raw = user.notification_prefs or list(settings.NOTIFICATION_DEFAULT_PREFS)
    out: list[NotificationChannel] = []
    seen: set[NotificationChannel] = set()
    for key in raw:
        try:
            channel = NotificationChannel(key)
        except ValueError:
            continue
        if channel in seen:
            continue
        seen.add(channel)
        out.append(channel)
    # Always retain the logger backstop so every dispatch yields *some*
    # ledger row, even when the user explicitly disabled every other
    # channel.
    if NotificationChannel.logger not in seen:
        out.append(NotificationChannel.logger)
    return out


def _persist_ledger(
    session: Session,
    *,
    user_id: uuid.UUID,
    ticket_id: uuid.UUID | None,
    kind: NotificationKind,
    body: str,
    channel: NotificationChannel,
    status_value: NotificationStatus,
    position: int | None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        ticket_id=ticket_id,
        kind=kind.value,
        body=body,
        channel=channel.value,
        status=status_value.value,
        position=position,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def dispatch(
    session: Session,
    *,
    user: User,
    payload: NotificationPayload,
) -> Notification | None:
    """Try each preferred channel until one accepts; record the result.

    Returns the persisted ``Notification`` row (or ``None`` when the user
    has no usable channels — a degenerate case impossible in practice
    because ``logger`` is always retained).
    """
    payload = payload.with_default_time()
    registry = get_registry()
    prefs = _user_prefs(user)

    delivered_via: NotificationChannel | None = None
    skipped: list[NotificationChannel] = []
    for channel in prefs:
        notifier = registry.get(channel)
        if notifier is None:
            continue
        try:
            ok = notifier.send(user=user, payload=payload)
        except Exception:  # noqa: BLE001 — never let a notifier crash dispatch
            logger.exception("notifier_failed", extra={"channel": channel.value})
            ok = False
        if ok:
            delivered_via = channel
            break
        skipped.append(channel)

    final_status = (
        NotificationStatus.delivered
        if delivered_via is not None
        else NotificationStatus.failed
    )
    final_channel = delivered_via or (
        skipped[-1] if skipped else NotificationChannel.logger
    )

    return _persist_ledger(
        session,
        user_id=user.id,
        ticket_id=payload.ticket_id,
        kind=payload.kind,
        body=payload.body,
        channel=final_channel,
        status_value=final_status,
        position=payload.position,
    )


def _ticket_position(session: Session, ticket: QueueEntry) -> int:
    statement = (
        select(func.count())
        .select_from(QueueEntry)
        .where(QueueEntry.service_item_id == ticket.service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(QueueEntry.ticket_number <= ticket.ticket_number)
    )
    raw = session.exec(statement).one()
    if isinstance(raw, tuple):
        raw = raw[0]
    return int(raw or 0)


def evaluate_smart_alerts_for_service_line(
    session: Session,
    *,
    service_item_id: uuid.UUID,
) -> list[Notification]:
    """Walk every active ticket on a service line and dispatch the
    appropriate alert (if any).

    Designed to run *after* the queue mutation has committed: each call
    is idempotent thanks to ``last_alert_position`` and safe to invoke
    even when nothing changed.
    """
    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(col(QueueEntry.user_id).is_not(None))
        .order_by(col(QueueEntry.ticket_number))
    ).all()

    fired: list[Notification] = []
    for ticket in rows:
        pos = _ticket_position(session, ticket)
        if pos < 1:
            continue
        decision = decide_alert(
            position=pos,
            last_alert_position=ticket.last_alert_position,
            top_k=settings.LIVENESS_TOP_K,
        )
        if decision is None:
            continue
        if ticket.user_id is None:
            continue  # walk-ins skipped (no registered recipient)
        user = session.get(User, ticket.user_id)
        if user is None or not user.is_active:
            continue
        result = dispatch(
            session,
            user=user,
            payload=NotificationPayload(
                kind=decision.kind,
                body=decision.body,
                ticket_id=ticket.id,
                service_item_id=service_item_id,
                position=pos,
            ),
        )
        if result is not None:
            fired.append(result)
        ticket.last_alert_position = pos
        session.add(ticket)

    if fired or any(t.last_alert_position for t in rows):
        # Commit so subsequent reads see the fresh ledger rows + alerts
        # state without leaking the open transaction across requests.
        session.commit()
    return fired


def list_user_notifications(
    session: Session, *, user: User, limit: int, offset: int
) -> tuple[list[Notification], int]:
    base = select(Notification).where(Notification.user_id == user.id)
    total_rows = session.exec(base).all()
    total = len(total_rows)
    page = (
        base.order_by(col(Notification.created_at).desc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(page).all()
    return list(rows), total


def update_prefs(
    session: Session, *, user: User, body: NotificationPrefsUpdate
) -> User:
    valid = {c.value for c in NotificationChannel}
    bad = [v for v in body.notification_prefs if v not in valid]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown notification channel(s): {bad}",
        )
    # Preserve order from the request; that's the user's preference.
    user.notification_prefs = list(body.notification_prefs)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def reset_prefs_default() -> list[str]:
    return list(settings.NOTIFICATION_DEFAULT_PREFS)


# Convenience re-export for hook sites that don't want to import the
# enum themselves.
__all__ = [
    "NotificationChannel",
    "NotificationKind",
    "dispatch",
    "evaluate_smart_alerts_for_service_line",
    "get_registry",
    "list_user_notifications",
    "reset_prefs_default",
    "set_registry",
    "update_prefs",
]
