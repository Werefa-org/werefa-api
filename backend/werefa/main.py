import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from werefa.api.error_handlers import register_exception_handlers
from werefa.api.main import api_router
from werefa.core.config import settings
from werefa.realtime.lifespan import realtime_lifespan

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


async def _reconcile_stuck_notifications() -> None:
    """Give an ending to rows the last process died holding.

    On a worker thread because the sweep is synchronous DB work, and in a
    blanket ``except`` because a database that is slow or unhappy at boot
    must not be the reason the app fails to start — the rows it would have
    resolved are still there for the next restart.
    """
    from werefa.notifications.application.reconcile import (
        reconcile_stuck_notifications,
    )

    try:
        await anyio.to_thread.run_sync(reconcile_stuck_notifications)
    except Exception:
        logger.exception("notification_reconcile_failed")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Imported here rather than at module scope so the notification stack
    # (and its worker threads) is only touched by processes that actually
    # serve requests — CLI entry points import ``werefa.main`` for the app
    # object alone.
    from werefa.notifications.application import service as notifications_service

    async with realtime_lifespan():
        # Started inside the realtime lifespan: a delivery that falls
        # through to the websocket channel needs the coordinator up, and
        # stopping first means no job is left mid-publish on the way down.
        delivery = notifications_service.get_delivery_queue()
        delivery.start()
        # After the queue is up, because a reconciled send goes straight
        # onto it — and before ``yield``, so a restart has already cleaned
        # up after its predecessor by the time it takes traffic.
        if settings.NOTIFICATION_RECONCILE_ON_STARTUP:
            await _reconcile_stuck_notifications()
        try:
            yield
        finally:
            delivery.stop(
                timeout=settings.NOTIFICATION_DELIVERY_SHUTDOWN_SECONDS
            )


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)
register_exception_handlers(app)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
