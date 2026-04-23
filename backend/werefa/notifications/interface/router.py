"""HTTP surface for smart pre-alerts (FR-07)."""

import uuid
from typing import Any

from fastapi import APIRouter, Query

from werefa.api.deps import CurrentUser, SessionDep
from werefa.identity.application import service as identity_service
from werefa.notifications.application import service as notifications_service
from werefa.shared.models import (
    NotificationPrefsUpdate,
    NotificationPublic,
    NotificationUnreadCount,
    NotificationsPublic,
    UserPublic,
)

router = APIRouter(prefix="/me", tags=["notifications"])
prefs_router = APIRouter(prefix="/users", tags=["notifications"])


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationPublic,
)
def mark_my_notification_read(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    notification_id: uuid.UUID,
) -> Any:
    row = notifications_service.mark_notification_read(
        session, user=current_user, notification_id=notification_id
    )
    return NotificationPublic.model_validate(row)


@router.get("/notifications/unread-count", response_model=NotificationUnreadCount)
def my_notification_unread_count(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    return NotificationUnreadCount(
        unread_count=notifications_service.count_unread_notifications(
            session, user=current_user
        )
    )


@router.get("/notifications", response_model=NotificationsPublic)
def list_my_notifications(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    rows, total = notifications_service.list_user_notifications(
        session, user=current_user, limit=limit, offset=offset
    )
    unread = notifications_service.count_unread_notifications(
        session, user=current_user
    )
    data = [NotificationPublic.model_validate(r) for r in rows]
    return NotificationsPublic(data=data, count=total, unread_count=unread)


@prefs_router.patch("/me/notifications", response_model=UserPublic)
def update_my_notification_prefs(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: NotificationPrefsUpdate,
) -> Any:
    return identity_service.to_user_public(
        notifications_service.update_prefs(
            session, user=current_user, body=body
        )
    )
