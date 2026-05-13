import asyncio
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from werefa.admin.application import service as admin_service
from werefa.api.deps import SessionDep, SuperUser
from werefa.core.config import settings
from werefa.realtime import lifespan
from werefa.shared.models import AdminUserRow, utcnow


class UserSuspendBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/system/health")
async def admin_system_health(
    *,
    session: SessionDep,
    _admin: SuperUser,
) -> dict[str, Any]:
    """Operational snapshot for dashboards (UC-15)."""
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    ws_total = 0
    ws_by_line: dict[str, int] = {}
    coordinator = lifespan.coordinator
    loop = lifespan.main_event_loop
    if coordinator is not None and loop is not None and loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(
            coordinator.websocket_subscriber_snapshot(),
            loop,
        )
        try:
            ws_total, ws_by_line = fut.result(timeout=2.0)
        except Exception:  # noqa: BLE001 — health must not fail hard
            ws_total, ws_by_line = 0, {}

    return {
        "database_reachable": db_ok,
        "realtime_redis_enabled": bool(
            settings.REALTIME_REDIS_URL not in (None, "")
        ),
        "websocket_subscribers_total": ws_total,
        "websocket_subscribers_by_line": ws_by_line,
        "environment": settings.ENVIRONMENT,
        "checked_at": utcnow().isoformat(),
    }


@router.get("/users/search", response_model=list[AdminUserRow])
def admin_search_users(
    *,
    session: SessionDep,
    _admin: SuperUser,
    q: str,
    limit: int = 20,
) -> Any:
    rows = admin_service.search_users_by_phone(session, q=q, limit=limit)
    return [
        AdminUserRow(
            id=u.id,
            email=u.email,
            phone_number=u.phone_number,
            is_active=u.is_active,
            is_suspended=u.is_suspended,
            user_type=u.user_type,
        )
        for u in rows
    ]


@router.post("/users/{user_id}/suspend", response_model=AdminUserRow)
def admin_suspend_user(
    *,
    session: SessionDep,
    _admin: SuperUser,
    user_id: uuid.UUID,
    body: UserSuspendBody,
) -> Any:
    u = admin_service.suspend_user(
        session, target_id=user_id, actor=_admin, reason=body.reason
    )
    return AdminUserRow(
        id=u.id,
        email=u.email,
        phone_number=u.phone_number,
        is_active=u.is_active,
        is_suspended=u.is_suspended,
        user_type=u.user_type,
    )


@router.post("/users/{user_id}/unsuspend", response_model=AdminUserRow)
def admin_unsuspend_user(
    *,
    session: SessionDep,
    _admin: SuperUser,
    user_id: uuid.UUID,
) -> Any:
    u = admin_service.unsuspend_user(session, target_id=user_id, actor=_admin)
    return AdminUserRow(
        id=u.id,
        email=u.email,
        phone_number=u.phone_number,
        is_active=u.is_active,
        is_suspended=u.is_suspended,
        user_type=u.user_type,
    )
