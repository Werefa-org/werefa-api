"""HTTP surface for verified reviews (FR-11, UC-08).

Routes are intentionally split between two prefixes:
- ``/tickets/{ticket_id}/reviews`` is a *write* endpoint scoped to the ticket
  that anchors the review. The ticket id is the natural idempotency key.
- ``/providers/{provider_id}/reviews`` and ``/providers/{provider_id}/rating``
  are *read* endpoints that surface aggregates without exposing internal ids.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Query

from werefa.api.deps import CurrentUser, SessionDep
from werefa.reviews.application import service as reviews_service
from werefa.shared.models import (
    ProviderRatingSummary,
    Review,
    ReviewCreate,
    ReviewPublic,
    ReviewsPublic,
    User,
)


def _review_to_public(session: SessionDep, review: Review) -> ReviewPublic:
    reviewer_name: str | None = None
    user = session.get(User, review.user_id)
    if user is not None:
        reviewer_name = user.full_name
    return ReviewPublic.model_validate(
        review, update={"reviewer_name": reviewer_name}
    )

ticket_router = APIRouter(prefix="/tickets", tags=["reviews"])
provider_router = APIRouter(prefix="/providers", tags=["reviews"])


@ticket_router.post(
    "/{ticket_id}/reviews", response_model=ReviewPublic
)
def create_review(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    body: ReviewCreate,
) -> Any:
    review = reviews_service.create_review(
        session,
        ticket_id=ticket_id,
        actor_user_id=current_user.id,
        body=body,
    )
    return _review_to_public(session, review)


@provider_router.get(
    "/{provider_id}/reviews", response_model=ReviewsPublic
)
def list_provider_reviews(
    *,
    session: SessionDep,
    provider_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    rows, count = reviews_service.list_reviews_for_provider(
        session, provider_id=provider_id, limit=limit, offset=offset
    )
    return ReviewsPublic(
        data=[_review_to_public(session, r) for r in rows], count=count
    )


@provider_router.get(
    "/{provider_id}/rating", response_model=ProviderRatingSummary
)
def get_provider_rating(
    *, session: SessionDep, provider_id: uuid.UUID
) -> Any:
    return reviews_service.provider_rating_summary(
        session, provider_id=provider_id
    )
