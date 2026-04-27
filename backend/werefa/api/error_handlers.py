import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse

from werefa.core.config import settings

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResponseValidationError)
    async def response_validation_handler(
        request: Request, exc: ResponseValidationError
    ) -> JSONResponse:
        logger.error("Response schema mismatch: %s", exc.errors())
        body: dict[str, Any] = {
            "detail": "The server could not build a response matching the API schema.",
        }
        if settings.ENVIRONMENT == "local":
            body["errors"] = exc.errors()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body,
        )
