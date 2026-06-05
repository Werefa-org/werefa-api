import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import emails  # type: ignore[import-untyped]
import jwt
from jinja2 import Template
from jwt.exceptions import InvalidTokenError

from werefa.core import security
from werefa.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EmailData:
    html_content: str
    subject: str


def _brand() -> str:
    """Customer-facing name for subjects and templates (not the API doc title)."""
    return settings.BRAND_NAME


def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    template_str = (
        Path(__file__).parent / "email-templates" / "build" / template_name
    ).read_text()
    html_content = Template(template_str).render(context)
    return html_content


def send_email(
    *,
    email_to: str,
    subject: str = "",
    html_content: str = "",
) -> None:
    assert settings.emails_enabled, "no provided configuration for email variables"
    message = emails.Message(
        subject=subject,
        html=html_content,
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )
    smtp_options = {"host": settings.SMTP_HOST, "port": settings.SMTP_PORT}
    if settings.SMTP_TLS:
        smtp_options["tls"] = True
    elif settings.SMTP_SSL:
        smtp_options["ssl"] = True
    if settings.SMTP_USER:
        smtp_options["user"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        smtp_options["password"] = settings.SMTP_PASSWORD
    response = message.send(to=email_to, smtp=smtp_options)
    logger.info(f"send email result: {response}")


def generate_test_email(email_to: str) -> EmailData:
    brand = _brand()
    subject = f"{brand} — Test email"
    html_content = render_email_template(
        template_name="test_email.html",
        context={"project_name": brand, "email": email_to},
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_reset_password_email(email_to: str, email: str, token: str) -> EmailData:
    brand = _brand()
    subject = f"{brand} — Reset your password"
    link = f"{settings.FRONTEND_HOST}/reset-password?token={token}"
    html_content = render_email_template(
        template_name="reset_password.html",
        context={
            "project_name": brand,
            "username": email,
            "email": email_to,
            "valid_hours": settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS,
            "link": link,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_queue_notification_email(
    *,
    email_to: str,
    subject: str,
    body: str,
    ticket_link: str | None = None,
    position: int | None = None,
) -> EmailData:
    html_content = render_email_template(
        template_name="queue_notification.html",
        context={
            "subject": subject,
            "body": body,
            "ticket_link": ticket_link,
            "position": position,
            "project_name": _brand(),
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def queue_notification_subject(kind: str) -> str:
    labels = {
        "head_to_counter": "Head to the counter soon",
        "you_are_next": "You're next in line",
        "now_serving": "You're being served now",
        "liveness_ping_request": "Share your location",
        "liveness_stale": "Location check needed",
        "line_chat_update": "New line chat message",
        "queue_cleared": "Queue closed",
    }
    label = labels.get(kind, "Queue update")
    return f"{_brand()} — {label}"


def ticket_deep_link(ticket_id: str) -> str:
    base = (settings.FRONTEND_HOST or "").rstrip("/")
    return f"{base}/me/tickets/{ticket_id}"


def generate_verification_verified_email(
    *,
    email_to: str,
    biz_name: str,
    dashboard_link: str,
) -> EmailData:
    subject = f"{_brand()} — {biz_name} is verified"
    html_content = render_email_template(
        template_name="verification_verified.html",
        context={
            "project_name": _brand(),
            "biz_name": biz_name,
            "dashboard_link": dashboard_link,
            "email": email_to,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_verification_rejected_email(
    *,
    email_to: str,
    biz_name: str,
    reason: str,
    documents_link: str,
) -> EmailData:
    subject = f"{_brand()} — Action needed for {biz_name}"
    html_content = render_email_template(
        template_name="verification_rejected.html",
        context={
            "project_name": _brand(),
            "biz_name": biz_name,
            "reason": reason,
            "documents_link": documents_link,
            "email": email_to,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_new_account_email(
    email_to: str, username: str, password: str
) -> EmailData:
    brand = _brand()
    subject = f"{brand} — Your Werefa account is ready"
    html_content = render_email_template(
        template_name="new_account.html",
        context={
            "project_name": brand,
            "username": username,
            "password": password,
            "email": email_to,
            "link": settings.FRONTEND_HOST,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_password_reset_token(email: str) -> str:
    delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    expires = now + delta
    exp = expires.timestamp()
    encoded_jwt = jwt.encode(
        {"exp": exp, "nbf": now, "sub": email},
        settings.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> str | None:
    try:
        decoded_token = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        return str(decoded_token["sub"])
    except InvalidTokenError:
        return None
