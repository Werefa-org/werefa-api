import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile

from werefa.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from werefa.identity.application import service as identity_service
from werefa.shared.models import (
    Message,
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    return identity_service.read_users(session, skip, limit)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    return identity_service.to_user_public(
        identity_service.create_user(session, user_in)
    )


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    return identity_service.to_user_public(
        identity_service.update_user_me(session, current_user, user_in)
    )


@router.post("/me/profile-image", response_model=UserPublic)
async def upload_user_profile_image(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    return await identity_service.upload_user_profile_image(
        session, current_user, file
    )


@router.post("/me/become-provider", response_model=UserPublic)
def become_provider(
    *, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Self-service ``customer → provider`` upgrade (HIGH-4).

    Returns the same payload as ``GET /users/me`` so a client can
    diff the ``user_type`` field locally without an extra round trip.
    The provider record this user creates afterwards still goes
    through the admin verification step (UC-10).
    """
    return identity_service.to_user_public(
        identity_service.become_provider(session, current_user)
    )


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    return identity_service.update_password_me(session, current_user, body)


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    return identity_service.to_user_public(current_user)


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    return identity_service.delete_user_me(session, current_user)


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    return identity_service.to_user_public(
        identity_service.register_user(session, user_in)
    )


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    return identity_service.to_user_public(
        identity_service.read_user_by_id(session, current_user, user_id)
    )


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    return identity_service.to_user_public(
        identity_service.update_user(session, user_id, user_in)
    )


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    return identity_service.delete_user(session, current_user, user_id)
