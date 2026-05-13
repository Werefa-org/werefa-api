"""Strike accrual + remote-join block enforcement (FR-12).

Public surface:

- :func:`record_no_show`: called from the queue service in the *same*
  transaction that flips a ticket to ``no_show``. Skips walk-ins, inserts
  a strike, and (if the threshold was just crossed) sets
  ``user.joins_blocked_until``.
- :func:`assert_remote_join_allowed`: called from ``join_queue_remote``
  before the row lock is taken. Raises ``HTTPException(403)`` with the
  block timestamp.
- :func:`get_self_strike_summary` / :func:`admin_unblock_user`: read +
  admin override.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel import Session, delete

from werefa.core.config import settings
from werefa.shared.models import (
    QueueEntry,
    User,
    UserStrike,
    UserStrikePublic,
    UserStrikesPublic,
)
from werefa.strikes.domain.strike_rules import (
    block_until_for_threshold,
    evaluate_block,
    window_start,
)
from werefa.strikes.infrastructure import repo as strikes_repo

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    # Centralised so tests can monkeypatch a single symbol.
    return datetime.now(timezone.utc)


def record_no_show(
    *,
    session: Session,
    ticket: QueueEntry,
    provider_id: uuid.UUID,
) -> UserStrike | None:
    """Persist a strike for ``ticket`` if it is a remote-join, registered
    user. Walk-ins (``ticket.user_id is None``) are silently skipped per
    FR-12 — only registered users can be penalised.

    Caller is responsible for the surrounding transaction; this function
    flushes so the new row is visible to the count query that follows but
    does **not** commit.
    """
    if ticket.user_id is None:
        return None

    user = session.get(User, ticket.user_id)
    if user is None:
        # Edge: user was hard-deleted between status update and strike
        # accrual. Don't fail the no-show flow over it; just log.
        logger.warning(
            "strike_skipped_user_missing",
            extra={"ticket_id": str(ticket.id), "user_id": str(ticket.user_id)},
        )
        return None

    strike = strikes_repo.insert_strike(
        session=session,
        user_id=user.id,
        ticket_id=ticket.id,
        provider_id=provider_id,
        kind="no_show",
    )
    logger.info(
        "strike_recorded",
        extra={
            "user_id": str(user.id),
            "ticket_id": str(ticket.id),
            "provider_id": str(provider_id),
        },
    )

    # If this strike just crossed the limit, materialise an explicit block
    # window so subsequent reads are O(1) and survive the rolling-window
    # boundary moving past older strikes.
    now = _utcnow()
    since = window_start(now=now, window_days=settings.STRIKE_WINDOW_DAYS)
    in_window = strikes_repo.count_strikes_since(
        session=session, user_id=user.id, since=since
    )
    if in_window >= settings.STRIKE_LIMIT:
        block_until = block_until_for_threshold(
            now=now, block_days=settings.STRIKE_BLOCK_DAYS
        )
        # Only extend, never shrink, an existing block.
        if (
            user.joins_blocked_until is None
            or user.joins_blocked_until < block_until
        ):
            user.joins_blocked_until = block_until
            session.add(user)
            logger.info(
                "join_block_set",
                extra={
                    "user_id": str(user.id),
                    "joins_blocked_until": block_until.isoformat(),
                    "strikes_in_window": in_window,
                },
            )

    return strike


def assert_remote_join_allowed(*, session: Session, user: User) -> None:
    """Raise 403 if the user is currently blocked from remote joins.

    Walk-ins never call this — the FR-12 spec is explicit that walk-in
    customers cannot be penalised.
    """
    now = _utcnow()
    since = window_start(now=now, window_days=settings.STRIKE_WINDOW_DAYS)
    in_window = strikes_repo.count_strikes_since(
        session=session, user_id=user.id, since=since
    )
    decision = evaluate_block(
        now=now,
        joins_blocked_until=user.joins_blocked_until,
        strikes_in_window=in_window,
        limit=settings.STRIKE_LIMIT,
    )
    if not decision.is_blocked:
        return

    # If we are blocked because the threshold *currently* sits at the limit
    # but no explicit block was previously persisted, materialise it now so
    # the next call doesn't have to re-derive it. Touching the user row in a
    # read endpoint is acceptable: the block is short-lived state.
    if decision.until is None:
        block_until = block_until_for_threshold(
            now=now, block_days=settings.STRIKE_BLOCK_DAYS
        )
        if (
            user.joins_blocked_until is None
            or user.joins_blocked_until < block_until
        ):
            user.joins_blocked_until = block_until
            session.add(user)
            session.commit()
            session.refresh(user)
        decision_until = user.joins_blocked_until
    else:
        decision_until = decision.until

    logger.info(
        "join_blocked",
        extra={
            "user_id": str(user.id),
            "reason": decision.reason,
            "joins_blocked_until": (
                decision_until.isoformat() if decision_until else None
            ),
            "strikes_in_window": in_window,
        },
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": (
                "You're temporarily blocked from joining queues remotely "
                "due to repeated no-shows. You can still walk in to a "
                "kiosk."
            ),
            "reason": decision.reason,
            "joins_blocked_until": (
                decision_until.isoformat() if decision_until else None
            ),
            "strikes_in_window": in_window,
            "limit": settings.STRIKE_LIMIT,
            "window_days": settings.STRIKE_WINDOW_DAYS,
        },
    )


def get_self_strike_summary(
    *, session: Session, user: User
) -> UserStrikesPublic:
    now = _utcnow()
    since = window_start(now=now, window_days=settings.STRIKE_WINDOW_DAYS)
    rows = strikes_repo.list_strikes_for_user(
        session=session, user_id=user.id, since=since, limit=50
    )
    return UserStrikesPublic(
        data=[UserStrikePublic.model_validate(r) for r in rows],
        count=len(rows),
        joins_blocked_until=user.joins_blocked_until,
        window_days=settings.STRIKE_WINDOW_DAYS,
        limit=settings.STRIKE_LIMIT,
    )


def admin_unblock_user(*, session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.joins_blocked_until = None
    # ``evaluate_block`` also rejects remote joins when
    # ``strikes_in_window >= STRIKE_LIMIT`` even after the explicit block
    # timestamp is cleared. An admin override must restore eligibility, so
    # the strike ledger for this user is reset (UC-16 governance unblock).
    session.exec(delete(UserStrike).where(UserStrike.user_id == user_id))
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("join_block_cleared_by_admin", extra={"user_id": str(user.id)})
    return user
