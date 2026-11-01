"""Domain error hierarchy and its mapping onto HTTP responses.

Services raise these and never import FastAPI's HTTPException. Every error response,
including framework-level ones (validation, unknown route), uses one envelope:

    {"error": {"code": "...", "message": "...", "details": ...}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BadRequest(DomainError):
    pass


class Unauthorized(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class Unprocessable(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unprocessable"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = jsonable_encoder(details)
    return {"error": error}


def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorized) else None
    return JSONResponse(
        error_body(exc.code, exc.message, exc.details), exc.status_code, headers=headers
    )


def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"loc": list(err["loc"]), "message": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        error_body("validation_error", "Request validation failed", details),
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return JSONResponse(error_body(code, str(exc.detail)), exc.status_code, headers=exc.headers)


def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", exc_info=exc)
    return JSONResponse(
        error_body("internal_error", "Internal server error"),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
