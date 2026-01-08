"""Shared helpers for non-dependency-injected JWT decoding.

These are used in WebSocket handlers and other entry points where FastAPI's
`Depends(...)` flow isn't available. HTTP routes should keep using
`werefa.api.deps.get_current_user`.
"""

import uuid

import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError

from werefa.core import security
from werefa.core.config import settings
from werefa.shared.models import TokenPayload


def user_id_from_token(token: str) -> uuid.UUID | None:
    """Best-effort parse of a JWT into a user UUID.

    Returns ``None`` if the token is invalid, unsigned with the wrong key,
    expired, or missing/has a malformed `sub` claim.
    """
    try:
        raw = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        data = TokenPayload(**raw)
    except (InvalidTokenError, ValidationError, ValueError):
        return None
    if not data.sub:
        return None
    try:
        return uuid.UUID(data.sub)
    except ValueError:
        return None
