"""Reviews application service: validates rules + persists with O(1) aggregation.

Concurrency note: the unique constraint on `review.ticket_id` is the
authoritative guard against double-submission. The service catches
``IntegrityError`` and surfaces a 409 so two simultaneous requests resolve to
"one success, one conflict" without races.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from werefa.reviews.domain.review_rules import (
    ReviewRuleError,
    validate_ticket_can_be_reviewed,
)
from werefa.reviews.infrastructure import repo as reviews_repo
from werefa.shared.models import (
    Provider,
    ProviderRatingSummary,
    QueueEntry,
    Review,
    ReviewCreate,
    ServiceItem,
)


def _provider_for_ticket(
    session: Session, ticket: QueueEntry
) -> tuple[Provider, ServiceItem]:
    svc = session.get(ServiceItem, ticket.service_item_id)
    if svc is None:  # FK guarantees it; defensive for mid-test inconsistencies.
        raise HTTPException(status_code=404, detail="Service not found")
    provider = session.get(Provider, svc.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider, svc


def create_review(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    body: ReviewCreate,
) -> Review:
    ticket = session.get(QueueEntry, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    existing = reviews_repo.get_review_for_ticket(
        session=session, ticket_id=ticket_id
    )

    try:
        validate_ticket_can_be_reviewed(
            ticket_user_id=ticket.user_id,
            ticket_status=ticket.status,
            actor_user_id=actor_user_id,
            has_existing_review=existing is not None,
        )
    except ReviewRuleError as e:
        # 409 for "already reviewed", 400 otherwise; keep the exact message for
        # the client to display.
        message = str(e)
        if "already" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=message
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message
        ) from e

    provider, svc = _provider_for_ticket(session, ticket)

    review = Review(
        ticket_id=ticket.id,
        user_id=actor_user_id,
        provider_id=provider.id,
        service_item_id=svc.id,
        rating=body.rating,
        was_estimate_accurate=body.was_estimate_accurate,
        comment=body.comment,
    )
    session.add(review)

    # Bump aggregate counters in the same transaction so reads stay O(1).
    provider.ratings_count = (provider.ratings_count or 0) + 1
    provider.ratings_sum = (provider.ratings_sum or 0) + body.rating
    if body.was_estimate_accurate:
        provider.estimate_accurate_count = (
            provider.estimate_accurate_count or 0
        ) + 1
    session.add(provider)

    try:
        session.commit()
    except IntegrityError as err:
        session.rollback()
        # Two parallel requests both passed the existence check; the unique
        # index on ticket_id resolved the race.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This ticket has already been reviewed",
        ) from err
    session.refresh(review)
    return review


def list_reviews_for_provider(
    session: Session,
    *,
    provider_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[Review], int]:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    rows, total = reviews_repo.list_reviews_for_provider(
        session=session,
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )
    return list(rows), total


def provider_rating_summary(
    session: Session, *, provider_id: uuid.UUID
) -> ProviderRatingSummary:
    if session.get(Provider, provider_id) is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    count, rating_sum, accurate = reviews_repo.aggregate_ratings_for_provider(
        session=session, provider_id=provider_id
    )
    if count == 0:
        return ProviderRatingSummary(
            provider_id=provider_id,
            ratings_count=0,
            rating_avg=None,
            estimate_accuracy_rate=None,
        )
    avg = round(rating_sum / count, 2)
    accuracy = round(accurate / count, 4)
    return ProviderRatingSummary(
        provider_id=provider_id,
        ratings_count=count,
        rating_avg=avg,
        estimate_accuracy_rate=accuracy,
    )
