import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlmodel import Session, col, func, select

from werefa.core import security
from werefa.core.config import settings
from werefa.core.security import get_password_hash, verify_password
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import TicketStatus, UserType
from werefa.shared.models import (
    Message,
    QueueEntry,
    Token,
    UpdatePassword,
    User,
    UserCreate,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
    utcnow,
)
from werefa.utils import (
    generate_new_account_email,
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)


def login_access_token(session: Session, email: str, password: str) -> Token:
    user = identity_repo.get_user_by_email(session=session, email=email)
    if user is None:
        verify_password(password, identity_repo.DUMMY_HASH)
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if user.is_suspended:
        raise HTTPException(
            status_code=403,
            detail="Account suspended",
        )
    now = utcnow()
    # if user.locked_until is not None and user.locked_until > now :
    #     raise HTTPException(
    #         status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    #         detail="Too many failed login attempts — try again later",
    #     )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    verified, updated_password_hash = verify_password(password, user.hashed_password)
    if not verified:
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
        session.add(user)
        session.commit()
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    user.failed_login_count = 0
    user.locked_until = None
    if updated_password_hash:
        user.hashed_password = updated_password_hash
    session.add(user)
    session.commit()
    session.refresh(user)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


def read_users(session: Session, skip: int, limit: int) -> UsersPublic:
    count = session.exec(select(func.count()).select_from(User)).one()
    users = session.exec(
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    ).all()
    return UsersPublic(data=list(users), count=count)


def create_user(session: Session, user_in: UserCreate) -> User:
    user = identity_repo.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = identity_repo.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


def update_user_me(session: Session, current_user: User, user_in: UserUpdateMe) -> User:
    """Profile edit only — role/identity changes go through dedicated
    endpoints so a `PATCH /users/me` body can never silently elevate
    the caller (HIGH-4)."""

    if user_in.email:
        existing_user = identity_repo.get_user_by_email(
            session=session, email=user_in.email
        )
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


def become_provider(session: Session, current_user: User) -> User:
    """Self-service upgrade from ``customer`` → ``provider`` (HIGH-4).

    The provider record they create afterwards still goes through the
    admin verification flow, so this endpoint by itself doesn't grant
    any public-facing presence — it just unlocks ``POST /providers/``
    so the user can register their business for review.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=400,
            detail="Administrator accounts already have provider privileges",
        )
    if current_user.user_type == UserType.provider.value:
        return current_user
    if current_user.user_type != UserType.customer.value:
        raise HTTPException(
            status_code=400,
            detail="Only customer accounts can upgrade to provider",
        )
    current_user.user_type = UserType.provider.value
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


def update_password_me(
    session: Session, current_user: User, body: UpdatePassword
) -> Message:
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    current_user.hashed_password = get_password_hash(body.new_password)
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


def delete_user_me(session: Session, current_user: User) -> Message:
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    # MED-4: refuse self-delete while active tickets exist; otherwise
    # the FK ``ON DELETE SET NULL`` would convert them into phantom
    # walk-ins that no one can clean up.
    active = session.exec(
        select(QueueEntry.id)
        .where(QueueEntry.user_id == current_user.id)
        .where(
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            )
        )
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "You still have an active queue ticket. Cancel or finish "
                "it before closing your account."
            ),
        )
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


def register_user(session: Session, user_in: UserRegister) -> User:
    user = identity_repo.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    return identity_repo.create_user(
        session=session, user_create=UserCreate.model_validate(user_in)
    )


def read_user_by_id(session: Session, current_user: User, user_id: uuid.UUID) -> User:
    # MED-7: handle the deleted-self edge first — a user looking up
    # their own (just-deleted) id otherwise falls into the non-super
    # 403 branch instead of the 404 they expect.
    if user_id == current_user.id:
        return current_user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def update_user(session: Session, user_id: uuid.UUID, user_in: UserUpdate) -> User:
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = identity_repo.get_user_by_email(
            session=session, email=user_in.email
        )
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    updated_user = identity_repo.update_user(
        session=session, db_user=db_user, user_in=user_in
    )
    # HIGH-3: keep ``is_superuser`` and ``user_type`` in lock-step in
    # both directions. Promotion sets user_type=admin; demotion drops
    # it back to ``customer`` (an admin who's no longer a superuser
    # is not a regular customer either, but ``customer`` is the only
    # safe default — the operator can re-issue ``provider`` afterwards
    # if they intended a sideways move).
    desired_type: str | None = None
    if updated_user.is_superuser and updated_user.user_type != UserType.admin.value:
        desired_type = UserType.admin.value
    elif (
        not updated_user.is_superuser
        and updated_user.user_type == UserType.admin.value
    ):
        desired_type = UserType.customer.value
    if desired_type is not None:
        updated_user.user_type = desired_type
        session.add(updated_user)
        session.commit()
        session.refresh(updated_user)
    return User.model_validate(updated_user)


def delete_user(session: Session, current_user: User, user_id: uuid.UUID) -> Message:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")


def recover_password(session: Session, email: str) -> Message:
    user = identity_repo.get_user_by_email(session=session, email=email)
    if user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


def reset_password(session: Session, token: str, new_password: str) -> Message:
    email = verify_password_reset_token(token=token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = identity_repo.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid token")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    identity_repo.update_user(
        session=session, db_user=user, user_in=UserUpdate(password=new_password)
    )
    return Message(message="Password updated successfully")


def recover_password_html_content(session: Session, email: str) -> tuple[str, str]:
    user = identity_repo.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )
    return email_data.subject, email_data.html_content
