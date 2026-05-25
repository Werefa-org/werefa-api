"""Persistence helpers for reviews.

The application service composes these with domain rules; routes never call
these directly.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func
from sqlmodel import Session, col, select

from werefa.shared.models import Review


def get_review_for_ticket(
    *, session: Session, ticket_id: uuid.UUID
) -> Review | None:
    statement = select(Review).where(Review.ticket_id == ticket_id)
    return session.exec(statement).first()


def aggregate_ratings_for_provider(
    *, session: Session, provider_id: uuid.UUID
) -> tuple[int, int, int]:
    """Return (count, rating_sum, estimate_accurate_count) from review rows."""
    count = session.exec(
        select(func.count())
        .select_from(Review)
        .where(Review.provider_id == provider_id)
    ).one()
    rating_sum = session.exec(
        select(func.coalesce(func.sum(Review.rating), 0)).where(
            Review.provider_id == provider_id
        )
    ).one()
    accurate = session.exec(
        select(func.count())
        .select_from(Review)
        .where(
            Review.provider_id == provider_id,
            Review.was_estimate_accurate == True,  # noqa: E712
        )
    ).one()
    return int(count or 0), int(rating_sum or 0), int(accurate or 0)


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
