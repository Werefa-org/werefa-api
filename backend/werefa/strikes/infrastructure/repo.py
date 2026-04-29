"""Persistence helpers for the strike ledger.

Pure data access — no rules, no HTTP. The application service composes these
with the rule functions and the active session/transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlmodel import Session, col, func, select

from werefa.shared.models import UserStrike


def insert_strike(
    *,
    session: Session,
    user_id: uuid.UUID,
    ticket_id: uuid.UUID,
    provider_id: uuid.UUID,
    kind: str = "no_show",
) -> UserStrike:
    """Insert a strike *without* committing.

    The caller is expected to be inside a wider transaction (e.g. the same
    one that flips the ticket status to ``no_show``) so the strike row only
    becomes visible if the status change does too.
    """
    row = UserStrike(
        user_id=user_id,
        ticket_id=ticket_id,
        provider_id=provider_id,
        kind=kind,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def count_strikes_since(
    *, session: Session, user_id: uuid.UUID, since: datetime
) -> int:
    """Count rows where ``created_at >= since``.

    NULL ``created_at`` is conservatively counted (it can only happen if
    something inserted a strike without the default, which is itself a bug
    worth surfacing).
    """
    statement = (
        select(func.count())
        .select_from(UserStrike)
        .where(UserStrike.user_id == user_id)
        .where(
            (col(UserStrike.created_at) >= since)
            | col(UserStrike.created_at).is_(None)
        )
    )
    raw = session.exec(statement).one()
    if isinstance(raw, tuple):
        raw = raw[0]
    return int(raw or 0)


def list_strikes_for_user(
    *,
    session: Session,
    user_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = 50,
) -> Sequence[UserStrike]:
    statement = select(UserStrike).where(UserStrike.user_id == user_id)
    if since is not None:
        statement = statement.where(col(UserStrike.created_at) >= since)
    statement = (
        statement.order_by(col(UserStrike.created_at).desc()).limit(limit)
    )
    return session.exec(statement).all()
