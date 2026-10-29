from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CACHE_OK = "public, max-age=300, s-maxage=21600"
CACHE_NONE = "no-store"


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def _error_response(request: Request, exc: ApiError) -> JSONResponse:
    body: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        body["details"] = exc.details
    body["request_id"] = getattr(request.state, "request_id", None)
    headers = {**exc.headers, "Cache-Control": CACHE_NONE}
    return JSONResponse({"error": body}, status_code=exc.status_code, headers=headers)


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        if response.status_code < 400 and request.url.path.startswith("/v1"):
            response.headers["Cache-Control"] = CACHE_OK
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        parameter = ".".join(str(p) for p in first["loc"][1:]) or None
        details: dict[str, Any] = {"parameter": parameter}
        message = f"Invalid value for '{parameter}': {first['msg']}"
        if first["type"] == "literal_error":
            allowed = re.findall(r"'([^']*)'", (first.get("ctx") or {}).get("expected", ""))
            details["allowed"] = allowed
            message = f"{parameter} must be one of: {', '.join(allowed)}"
        return _error_response(request, ApiError(422, "invalid_parameter", message, details))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(request, ApiError(404, "route_not_found", "No such endpoint."))
        return _error_response(request, ApiError(exc.status_code, "internal_error", str(exc.detail)))

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(request, ApiError(500, "internal_error", "Unexpected error."))
