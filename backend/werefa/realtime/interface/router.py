import asyncio
import logging
import uuid

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
from werefa.shared.models import ServiceItem, TokenPayload, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["realtime"])


@router.websocket("/service-items/{service_item_id}/stream")
async def queue_service_item_stream(
    websocket: WebSocket,
    service_item_id: uuid.UUID,
    token: str = Query(..., description="Bearer JWT (access token)"),
) -> None:
    await websocket.accept()
    c = lifespan.coordinator
    if c is None:
        await websocket.close(
            code=status.WS_1011_INTERNAL_ERROR, reason="Realtime not initialised"
        )
        return

    try:
        raw = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        data = TokenPayload(**raw)
    except (InvalidTokenError, ValidationError, ValueError):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token"
        )
        return
    if not data.sub:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid subject"
        )
        return

    try:
        user_uuid = uuid.UUID(data.sub)
    except ValueError:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid subject"
        )
        return

    with Session(engine) as session:
        user = session.get(User, user_uuid)
        if not user or not user.is_active:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Inactive or missing user"
            )
            return
        svc = session.get(ServiceItem, service_item_id)
        if not svc:
            await websocket.close(code=1000, reason="Service not found")
            return
        try:
            ensure_provider_staff(
                session=session, current_user=user, provider_id=svc.provider_id
            )
        except HTTPException:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Forbidden"
            )
            return

    q, unsubscribe = await c.hub.subscribe(service_item_id)
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
