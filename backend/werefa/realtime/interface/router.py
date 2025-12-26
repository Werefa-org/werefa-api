import asyncio
import logging
import uuid
from collections.abc import Callable

import jwt
from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session
from starlette.websockets import WebSocketDisconnect, WebSocketState

from werefa.api.deps import ensure_provider_staff
from werefa.core import security
from werefa.core.config import settings
from werefa.core.db import engine
from werefa.realtime import lifespan
from werefa.realtime.domain.events import QueueEventV1
from werefa.shared.models import QueueEntry, ServiceItem, TokenPayload, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["realtime"])


async def _close_socket(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.close(code=code, reason=reason)


def _user_id_from_token(token: str) -> uuid.UUID | None:
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


def _message_for_ticket(message: str, ticket_id: uuid.UUID) -> bool:
    try:
        event = QueueEventV1.model_validate_json(message)
    except ValidationError:
        return False
    return event.ticket_id == ticket_id


async def _stream_service_messages(
    websocket: WebSocket,
    service_item_id: uuid.UUID,
    *,
    message_filter: Callable[[str], bool],
) -> None:
    coordinator = lifespan.coordinator
    if coordinator is None:
        await _close_socket(
            websocket,
            code=status.WS_1011_INTERNAL_ERROR,
            reason="Realtime not initialised",
        )
        return
    q, unsubscribe = await coordinator.hub.subscribe(service_item_id)
    try:
        while True:
            recv_task = asyncio.create_task(websocket.receive())
            get_task: asyncio.Task[str] = asyncio.create_task(q.get())
            done, _ = await asyncio.wait(
                {recv_task, get_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if recv_task in done:
                if not get_task.done():
                    get_task.cancel()
                try:
                    rmsg = recv_task.result()
                except WebSocketDisconnect:
                    break
                if rmsg.get("type") == "websocket.disconnect":
                    break
                continue
            if not recv_task.done():
                recv_task.cancel()
            try:
                message = get_task.result()
            except Exception:
                logger.exception("Queue get failed")
                break
            if not message_filter(message):
                continue
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            try:
                await websocket.send_text(message)
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await unsubscribe()
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


@router.websocket("/service-items/{service_item_id}/stream")
async def queue_service_item_stream(
    websocket: WebSocket,
    service_item_id: uuid.UUID,
    token: str = Query(..., description="Bearer JWT (access token)"),
) -> None:
    await websocket.accept()
    user_uuid = _user_id_from_token(token)
    if user_uuid is None:
        await _close_socket(
            websocket,
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid token",
        )
        return
    with Session(engine) as session:
        user = session.get(User, user_uuid)
        if not user or not user.is_active:
            await _close_socket(
                websocket,
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Inactive or missing user",
            )
            return
        svc = session.get(ServiceItem, service_item_id)
        if not svc:
            await _close_socket(websocket, code=1000, reason="Service not found")
            return
        try:
            ensure_provider_staff(
                session=session, current_user=user, provider_id=svc.provider_id
            )
        except HTTPException:
            await _close_socket(
                websocket,
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Forbidden",
            )
            return
    await _stream_service_messages(
        websocket,
        service_item_id,
        message_filter=lambda _message: True,
    )


@router.websocket("/tickets/{ticket_id}/stream")
async def queue_ticket_stream(
    websocket: WebSocket,
    ticket_id: uuid.UUID,
    token: str = Query(..., description="Bearer JWT (access token)"),
) -> None:
    await websocket.accept()
    user_uuid = _user_id_from_token(token)
    if user_uuid is None:
        await _close_socket(
            websocket,
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid token",
        )
        return
    with Session(engine) as session:
        user = session.get(User, user_uuid)
        if not user or not user.is_active:
            await _close_socket(
                websocket,
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Inactive or missing user",
            )
            return
        ticket = session.get(QueueEntry, ticket_id)
        if ticket is None:
            await _close_socket(websocket, code=1000, reason="Ticket not found")
            return
        svc = session.get(ServiceItem, ticket.service_item_id)
        if svc is None:
            await _close_socket(websocket, code=1000, reason="Service not found")
            return
        if not user.is_superuser and ticket.user_id != user.id:
            try:
                ensure_provider_staff(
                    session=session, current_user=user, provider_id=svc.provider_id
                )
            except HTTPException:
                await _close_socket(
                    websocket,
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Forbidden",
                )
                return
        service_item_id = ticket.service_item_id
    await _stream_service_messages(
        websocket,
        service_item_id,
        message_filter=lambda message: _message_for_ticket(message, ticket_id),
    )
