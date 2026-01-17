from fastapi import APIRouter

from werefa.api.routes import private, utils
from werefa.core.config import settings
from werefa.identity.interface import login_router, users_router
from werefa.providers.interface import router as providers_router
from werefa.queue.interface import router as queue_router
from werefa.realtime.interface import router as realtime_router
from werefa.reviews.interface import (
    provider_router as reviews_provider_router,
    ticket_router as reviews_ticket_router,
)
from werefa.service_items.interface import router as service_items_router

api_router = APIRouter()
api_router.include_router(login_router.router)
api_router.include_router(users_router.router)
api_router.include_router(utils.router)
api_router.include_router(providers_router.router)
api_router.include_router(service_items_router.router)
api_router.include_router(queue_router.router)
api_router.include_router(reviews_ticket_router)
api_router.include_router(reviews_provider_router)
api_router.include_router(realtime_router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
