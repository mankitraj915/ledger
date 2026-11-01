"""Structured (JSON-lines) logging and per-request correlation.

Every log line emitted while handling a request carries that request's id, so a
single settlement can be traced from the access log line to its domain event.
"""

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
REQUEST_ID_HEADER = "X-Request-ID"

log = logging.getLogger("ledger.http")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        # Anything passed via `extra=` becomes a top-level field.
        payload.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Requests are logged by our middleware; uvicorn's access log would duplicate them.
    logging.getLogger("uvicorn.access").disabled = True


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        fields: dict[str, object] = {"method": request.method, "path": request.url.path}
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Logged here, while the request id is still bound. The 500 envelope
                # itself comes from the outermost error handler in app.errors.
                fields.update(status=500, duration_ms=_elapsed_ms(started))
                log.exception("http.request", extra=fields)
                raise
            fields.update(status=response.status_code, duration_ms=_elapsed_ms(started))
            log.info("http.request", extra=fields)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
