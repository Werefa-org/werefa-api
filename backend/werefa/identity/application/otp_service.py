"""Email OTP login stub (US-SYS-00) — stores hashed codes; logs plaintext in local."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from werefa.core import security
from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.models import EmailOtpChallenge, Message, Token, User, utcnow

logger = logging.getLogger(__name__)


def _hash_code(code: str) -> str:
    raw = f"{code}:{settings.SECRET_KEY}".encode()
    return hashlib.sha256(raw).hexdigest()


def request_email_otp(session: Session, email: str) -> Message:
    user = identity_repo.get_user_by_email(session=session, email=email)
    if user is None:
        return Message(message="If that email is registered, we sent a one-time code")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account suspended")
    code = f"{secrets.randbelow(10**6):06d}"
    row = EmailOtpChallenge(
        email=user.email,
        code_hash=_hash_code(code),
        expires_at=utcnow() + timedelta(minutes=settings.OTP_TTL_MINUTES),
    )
    session.add(row)
    session.commit()
    if settings.ENVIRONMENT == "local":
        logger.warning(
            "otp_login_dev_code",
            extra={"email": user.email, "code": code},
        )
    return Message(message="If that email is registered, we sent a one-time code")


def verify_email_otp(session: Session, email: str, code: str) -> Token:
    user = identity_repo.get_user_by_email(session=session, email=email)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid code")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account suspended")
    h = _hash_code(code)
    row = session.exec(
        select(EmailOtpChallenge)
        .where(EmailOtpChallenge.email == user.email)
        .where(EmailOtpChallenge.consumed_at.is_(None))
        .where(col(EmailOtpChallenge.expires_at) > utcnow())
        .order_by(col(EmailOtpChallenge.created_at).desc())
    ).first()
    if row is None or row.code_hash != h:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )
    row.consumed_at = utcnow()
    session.add(row)
    user.failed_login_count = 0
    user.locked_until = None
    session.add(user)
    session.commit()
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(user.id, expires_delta=expires)
    )
