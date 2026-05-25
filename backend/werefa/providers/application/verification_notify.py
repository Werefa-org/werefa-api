"""Email owner when a provider is verified or rejected."""

from __future__ import annotations

import logging
import uuid

from sqlmodel import Session, select

from werefa.core.config import settings
from werefa.shared.enums import MembershipRole
from werefa.shared.models import Provider, ProviderMembership, User
from werefa.utils import (
    EmailData,
    generate_verification_rejected_email,
    generate_verification_verified_email,
    send_email,
)

logger = logging.getLogger(__name__)


def _owner_for_provider(session: Session, provider_id: uuid.UUID) -> User | None:
    row = session.exec(
        select(User)
        .join(ProviderMembership, ProviderMembership.user_id == User.id)
        .where(
            ProviderMembership.provider_id == provider_id,
            ProviderMembership.role == MembershipRole.owner.value,
        )
    ).first()
    return row


def _recipient_email(provider: Provider, owner: User | None) -> str | None:
    if provider.biz_email and str(provider.biz_email).strip():
        return str(provider.biz_email).strip()
    if owner and owner.email:
        return str(owner.email)
    return None


def notify_provider_verified(session: Session, provider: Provider) -> None:
    if not settings.emails_enabled:
        logger.info(
            "Skipping verification email for %s (emails disabled)",
            provider.slug,
        )
        return
    owner = _owner_for_provider(session, provider.id)
    email_to = _recipient_email(provider, owner)
    if not email_to:
        logger.warning("No email for provider %s verification notice", provider.id)
        return
    dashboard = f"{settings.FRONTEND_HOST.rstrip('/')}/dashboard"
    data: EmailData = generate_verification_verified_email(
        email_to=email_to,
        biz_name=provider.biz_name,
        dashboard_link=dashboard,
    )
    try:
        send_email(
            email_to=email_to,
            subject=data.subject,
            html_content=data.html_content,
        )
    except Exception:
        logger.exception("Failed to send verification approved email")


def notify_provider_rejected(
    session: Session, provider: Provider, *, reason: str
) -> None:
    if not settings.emails_enabled:
        logger.info(
            "Skipping rejection email for %s (emails disabled)",
            provider.slug,
        )
        return
    owner = _owner_for_provider(session, provider.id)
    email_to = _recipient_email(provider, owner)
    if not email_to:
        logger.warning("No email for provider %s rejection notice", provider.id)
        return
    docs_link = (
        f"{settings.FRONTEND_HOST.rstrip('/')}/dashboard/settings/documents"
    )
    data: EmailData = generate_verification_rejected_email(
        email_to=email_to,
        biz_name=provider.biz_name,
        reason=reason,
        documents_link=docs_link,
    )
    try:
        send_email(
            email_to=email_to,
            subject=data.subject,
            html_content=data.html_content,
        )
    except Exception:
        logger.exception("Failed to send verification rejected email")
