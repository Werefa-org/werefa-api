"""Notification dispatch + ledger + smart-alert orchestration (FR-07)."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.core.db import engine
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
    utcnow,
)

logger = logging.getLogger(__name__)

# Queue-critical alerts always attempt email when it is in the user's
# prefs, even if websocket already delivered (in-app + inbox + mail).
EMAIL_COPY_KINDS: frozenset[NotificationKind] = frozenset(
    {
        NotificationKind.head_to_counter,
        NotificationKind.you_are_next,
        NotificationKind.now_serving,
        NotificationKind.liveness_ping_request,
        NotificationKind.liveness_stale,
        NotificationKind.line_chat_update,
        NotificationKind.queue_cleared,
    }
)

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


def _try_email_copy(
    registry: dict[NotificationChannel, Notifier],
    *,
    user: User,
    payload: NotificationPayload,
) -> None:
    """Send email without changing the primary ledger channel."""
    from werefa.core.config import settings

    if not settings.emails_enabled:
        return
    if payload.kind not in EMAIL_COPY_KINDS:
        return
    prefs = _user_prefs(user)
    if NotificationChannel.email not in prefs:
        return
    notifier = registry.get(NotificationChannel.email)
    if notifier is None:
        return
    try:
        notifier.send(user=user, payload=payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "notification_email_copy_failed",
            extra={"kind": payload.kind.value, "user_id": str(user.id)},
        )


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
    defer_email = (
        payload.kind in EMAIL_COPY_KINDS
        and NotificationChannel.email in prefs
    )

    delivered_via: NotificationChannel | None = None
    skipped: list[NotificationChannel] = []
    for channel in prefs:
        if defer_email and channel == NotificationChannel.email:
            continue
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

    row = _persist_ledger(
        session,
        user_id=user.id,
        ticket_id=payload.ticket_id,
        kind=payload.kind,
        body=payload.body,
        channel=final_channel,
        status_value=final_status,
        position=payload.position,
    )
    if defer_email:
        _try_email_copy(registry, user=user, payload=payload)
    return row


STAFF_YOU_ARE_NEXT_BODY = "You are next in the queue!!!!"


def notify_ticket_staff_you_are_next(
    session: Session,
    *,
    ticket: QueueEntry,
    service_item_id: uuid.UUID,
) -> Notification | None:
    """Staff-triggered alert: customer is next in line (app users only)."""
    if ticket.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Walk-in customers cannot receive app notifications.",
        )
    if ticket.status != TicketStatus.waiting.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only waiting customers can be notified.",
        )
    user = session.get(User, ticket.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This customer cannot receive notifications.",
        )
    pos = _ticket_position(session, ticket)
    result = dispatch(
        session,
        user=user,
        payload=NotificationPayload(
            kind=NotificationKind.you_are_next,
            body=STAFF_YOU_ARE_NEXT_BODY,
            ticket_id=ticket.id,
            service_item_id=service_item_id,
            position=pos,
        ),
    )
    ticket.last_alert_position = 1
    session.add(ticket)
    session.commit()
    if result is not None:
        session.refresh(result)
    return result


def notify_ticket_now_serving(
    session: Session,
    *,
    ticket: QueueEntry,
    service_item_id: uuid.UUID,
) -> Notification | None:
    """Alert the customer whose ticket was just called to the counter."""
    if ticket.user_id is None:
        return None
    user = session.get(User, ticket.user_id)
    if user is None or not user.is_active:
        return None
    return dispatch(
        session,
        user=user,
        payload=NotificationPayload(
            kind=NotificationKind.now_serving,
            body="You're being served now — please come to the counter.",
            ticket_id=ticket.id,
            service_item_id=service_item_id,
            position=1,
        ),
    )


def notify_line_chat_staff_message(
    session: Session,
    *,
    service_item_id: uuid.UUID,
    body_text: str,
    author_label: str,
    author_user_id: uuid.UUID,
) -> list[Notification]:
    """Inbox alerts for customers on the line when staff posts in chat."""
    rows = session.exec(
        select(QueueEntry)
        .where(QueueEntry.service_item_id == service_item_id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
        .where(col(QueueEntry.user_id).is_not(None))
    ).all()
    preview = body_text.strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."
    message_body = f"{author_label}: {preview}"
    fired: list[Notification] = []
    for ticket in rows:
        if ticket.user_id is None or ticket.user_id == author_user_id:
            continue
        user = session.get(User, ticket.user_id)
        if user is None or not user.is_active:
            continue
        result = dispatch(
            session,
            user=user,
            payload=NotificationPayload(
                kind=NotificationKind.line_chat_update,
                body=message_body,
                ticket_id=ticket.id,
                service_item_id=service_item_id,
            ),
        )
        if result is not None:
            fired.append(result)
    return fired


def count_unread_notifications(session: Session, *, user: User) -> int:
    raw = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id)
        .where(col(Notification.read_at).is_(None))
    ).one()
    return int(raw[0] if isinstance(raw, tuple) else raw)


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
    from werefa.queue.application import liveness_service
    from werefa.realtime.notify import notify_queue_subscribers

    liveness_touched = liveness_service.sync_liveness_for_service_line(
        session, service_item_id
    )

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

    has_serving_ahead = any(
        t.status == TicketStatus.serving.value for t in rows
    )

    fired: list[Notification] = []
    for ticket in rows:
        if ticket.status == TicketStatus.serving.value:
            continue
        pos = _ticket_position(session, ticket)
        if pos < 1:
            continue
        decision = decide_alert(
            position=pos,
            last_alert_position=ticket.last_alert_position,
            top_k=settings.LIVENESS_TOP_K,
            has_serving_ahead=has_serving_ahead,
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

    should_commit = (
        bool(fired)
        or liveness_touched
        or any(t.last_alert_position is not None for t in rows)
    )
    if should_commit:
        # Commit so subsequent reads see the fresh ledger rows + alerts
        # state without leaking the open transaction across requests.
        session.commit()

    if liveness_touched:
        notify_queue_subscribers(session, service_item_id, reason="liveness")

    return fired


def run_evaluate_smart_alerts_for_service_line(service_item_id: uuid.UUID) -> None:
    """Background-task entry point: opens its own DB session.

    Never pass the request-scoped ``Session`` into ``BackgroundTasks`` — it is
    closed when the HTTP response finishes, which leaves pooled connections in
    a bad state and surfaces as intermittent 500s on position pings.
    """
    try:
        from sqlmodel import Session

        with Session(engine) as session:
            evaluate_smart_alerts_for_service_line(
                session, service_item_id=service_item_id
            )
    except Exception:
        logger.exception(
            "Smart alerts failed after position ping",
            extra={"service_item_id": str(service_item_id)},
        )


def mark_notification_read(
    session: Session, *, user: User, notification_id: uuid.UUID
) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    row.read_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_user_notifications(
    session: Session, *, user: User, limit: int, offset: int
) -> tuple[list[Notification], int]:
    # MED-3: COUNT(*) instead of materialising every row — the new
    # ``(user_id, created_at)`` index makes both reads a single index
    # scan.
    total_raw = session.exec(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id)
    ).one()
    total = int(total_raw[0] if isinstance(total_raw, tuple) else total_raw)
    page = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(col(Notification.created_at).desc())
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
    "EMAIL_COPY_KINDS",
    "count_unread_notifications",
    "dispatch",
    "evaluate_smart_alerts_for_service_line",
    "notify_line_chat_staff_message",
    "notify_ticket_now_serving",
    "notify_ticket_staff_you_are_next",
    "STAFF_YOU_ARE_NEXT_BODY",
    "run_evaluate_smart_alerts_for_service_line",
    "get_registry",
    "list_user_notifications",
    "mark_notification_read",
    "reset_prefs_default",
    "set_registry",
    "update_prefs",
]
