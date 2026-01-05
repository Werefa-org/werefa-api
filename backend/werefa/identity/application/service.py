import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlmodel import Session, col, func, select

from werefa.core import security
from werefa.core.config import settings
from werefa.core.security import get_password_hash, verify_password
from werefa.identity.infrastructure import repo as identity_repo
from werefa.shared.enums import UserType
from werefa.shared.models import (
    Message,
    Token,
    UpdatePassword,
    User,
    UserCreate,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from werefa.utils import (
    generate_new_account_email,
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)


def login_access_token(session: Session, email: str, password: str) -> Token:
    user = identity_repo.authenticate(session=session, email=email, password=password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
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
    if user_in.email:
        existing_user = identity_repo.get_user_by_email(
            session=session, email=user_in.email
        )
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    data = user_in.model_dump(exclude_unset=True)
    if "user_type" in data:
        if data["user_type"] != "provider":
            raise HTTPException(
                status_code=400,
                detail="Only upgrading to provider is supported from this endpoint",
            )
        if current_user.is_superuser:
            raise HTTPException(
                status_code=400,
                detail="Administrator accounts cannot change type here",
            )
        if current_user.user_type != UserType.customer.value:
            raise HTTPException(
                status_code=400,
                detail="Only customer accounts can switch to provider this way",
            )
        data["user_type"] = UserType.provider.value
    current_user.sqlmodel_update(data)
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
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
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
    if updated_user.is_superuser and updated_user.user_type != UserType.admin.value:
        updated_user.user_type = UserType.admin.value
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
