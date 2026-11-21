"""Safe exception handlers for the FastAPI HTTP shell."""

from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .schemas import ErrorResponse

logger = logging.getLogger(__name__)

_SAFE_HTTP_MAP: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Invalid request."),
    401: ("unauthorized", "Invalid authentication."),
    403: ("forbidden", "Access denied."),
    404: ("not_found", "Resource not found."),
    405: ("method_not_allowed", "Method not allowed."),
    422: ("validation_error", "Request validation failed."),
    503: ("service_unavailable", "Service is currently unavailable."),
}


def install_error_handlers(app: FastAPI) -> None:
    """Install secret-safe HTTP, validation, and fallback exception handlers."""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        category, default_detail = _SAFE_HTTP_MAP.get(
            exc.status_code, ("http_error", "Request failed.")
        )
        headers = dict(exc.headers) if exc.headers else {}
        if exc.status_code == 401 and "WWW-Authenticate" not in headers:
            headers["WWW-Authenticate"] = "Bearer"

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=category, detail=default_detail).model_dump(),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error="validation_error",
                detail="Request parameters or body failed validation.",
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("Unhandled internal HTTP error")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="An unexpected internal error occurred.",
            ).model_dump(),
        )
