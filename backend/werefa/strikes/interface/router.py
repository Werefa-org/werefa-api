"""HTTP surface for the strike system (FR-12).

Two routers, two prefixes:

- ``me_router`` lives under ``/me/strikes`` and is the user-facing read.
- ``admin_router`` lives under ``/admin/users/{user_id}/...`` and groups
  admin-only overrides; this is the first endpoint of what will become a
  fuller admin namespace in Phase 14.
"""

import uuid
from typing import Any

from fastapi import APIRouter

from werefa.api.deps import CurrentUser, SessionDep, SuperUser
from werefa.shared.models import UserPublic, UserStrikesPublic
from werefa.strikes.application import service as strikes_service

me_router = APIRouter(prefix="/me", tags=["strikes"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@me_router.get("/strikes", response_model=UserStrikesPublic)
def get_my_strikes(
    *, session: SessionDep, current_user: CurrentUser
) -> Any:
    return strikes_service.get_self_strike_summary(
        session=session, user=current_user
    )


@admin_router.post(
    "/users/{user_id}/unblock", response_model=UserPublic
)
def admin_unblock_user(
    *,
    session: SessionDep,
    _admin: SuperUser,
    user_id: uuid.UUID,
) -> Any:
    return strikes_service.admin_unblock_user(
        session=session, user_id=user_id
    )
