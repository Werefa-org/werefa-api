from fastapi import APIRouter

from werefa.api.routes import (
    login,
    private,
    providers,
    service_items,
    tickets,
    users,
    utils,
)
from werefa.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(providers.router)
api_router.include_router(service_items.router)
api_router.include_router(tickets.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
