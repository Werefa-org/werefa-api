"""Persistence helpers for reviews.

The application service composes these with domain rules; routes never call
these directly.
"""

import uuid
from collections.abc import Sequence

from sqlmodel import Session, col, select

from werefa.shared.models import Review


def get_review_for_ticket(
    *, session: Session, ticket_id: uuid.UUID
) -> Review | None:
    statement = select(Review).where(Review.ticket_id == ticket_id)
    return session.exec(statement).first()


def list_reviews_for_provider(
    *,
    session: Session,
    provider_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[Sequence[Review], int]:
    base = select(Review).where(Review.provider_id == provider_id)

    count_rows = session.exec(base).all()
    total = len(count_rows)

    page = (
        base.order_by(col(Review.created_at).desc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(page).all()
    return rows, total
