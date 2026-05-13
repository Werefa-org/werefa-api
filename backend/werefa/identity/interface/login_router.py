from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

from werefa.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from werefa.identity.application import otp_service
from werefa.identity.application import service as identity_service
from werefa.shared.models import Message, NewPassword, OtpRequest, OtpVerify, Token, UserPublic

router = APIRouter(tags=["login"])


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    return identity_service.login_access_token(
        session, form_data.username, form_data.password
    )


@router.post("/login/otp/request", response_model=Message)
def login_otp_request(session: SessionDep, body: OtpRequest) -> Message:
    return otp_service.request_email_otp(session, body.email)


@router.post("/login/otp/verify", response_model=Token)
def login_otp_verify(session: SessionDep, body: OtpVerify) -> Token:
    return otp_service.verify_email_otp(session, body.email, body.code)


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    return identity_service.recover_password(session, email)


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    return identity_service.reset_password(session, body.token, body.new_password)


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    subject, html_content = identity_service.recover_password_html_content(
        session, email
    )
    return HTMLResponse(content=html_content, headers={"subject:": subject})
