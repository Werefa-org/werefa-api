import uuid
from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from werefa.core import security
from werefa.core.config import settings
from werefa.core.db import engine
from werefa.providers.infrastructure import repo as provider_repo
from werefa.shared.enums import MembershipRole
from werefa.shared.models import TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _decode_token_user(session: Session, token: str) -> User | None:
    """Resolve a JWT to an active ``User`` or return ``None`` on any failure.

    Used by the optional-auth dependency below so endpoints that *want*
    to behave differently for known users (without forcing auth) can do
    so without sprinkling try/except blocks at each call site.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        return None
    user = session.get(User, token_data.sub)
    if user is None or not user.is_active:
        return None
    return user


_optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,
)


def get_optional_current_user(
    session: SessionDep,
    token: Annotated[str | None, Depends(_optional_oauth2)] = None,
) -> User | None:
    """Return the authenticated user if a valid token was supplied,
    otherwise ``None``. Never raises — the route decides what to do
    when the caller is anonymous."""
    if not token:
        return None
    return _decode_token_user(session, token)


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


SuperUser = Annotated[User, Depends(get_current_active_superuser)]


def ensure_provider_staff(
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> None:
    if current_user.is_superuser:
        return
    m = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=current_user.id
    )
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this provider",
        )


def ensure_provider_owner_or_super(
    session: SessionDep,
    current_user: CurrentUser,
    provider_id: uuid.UUID,
) -> None:
    if current_user.is_superuser:
        return
    m = provider_repo.get_membership(
        session=session, provider_id=provider_id, user_id=current_user.id
    )
    if m is None or m.role != MembershipRole.owner.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner or administrator access required",
        )
