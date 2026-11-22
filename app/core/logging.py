"""Logging setup and X-Request-ID correlation for the API.

Every log record emitted while a request is being handled carries its
``request_id``, so a line in the log can be matched with the id the client got
back in the ``X-Request-ID`` response header. Behind Nginx that id is the same
one Nginx logs (``$request_id``), which joins the logs of both containers.
"""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
import logging
import logging.config
import re
from typing import Final
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ErrorResponseBuilder = Callable[[Scope, Exception], Awaitable[JSONResponse]]

# Header used to carry the correlation id, in and out.
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

# Placeholder used outside a request (startup logs, background tasks).
NO_REQUEST_ID: Final[str] = "-"

# Nginx sends a 32-character hex id. Anything else is replaced: a client must
# not be able to inject line breaks or unbounded text into the logs.
_VALID_REQUEST_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._-]{1,64}")

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)

# Logger for the request lifecycle events owned by this module.
logger: Final[logging.Logger] = logging.getLogger("app.request")

_LOG_FORMAT: Final[str] = (
    "%(asctime)s %(levelname)s %(name)s [request_id=%(request_id)s] %(message)s"
)

# dictConfig replaces the root handlers, so it must run once per process: a
# second call would remove handlers installed later (for example by pytest's
# caplog).
_configured: bool = False


def sanitize_for_log(value: str, max_len: int = 120) -> str:
    """Escape control/non-ASCII characters (CR/LF, ANSI, U+2028...) and truncate."""
    return value.encode("unicode_escape").decode("ascii")[:max_len]


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record that is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging(level: str) -> None:
    """
    Configure logging once per process.

    The level comes from the ``LOG_LEVEL`` setting, so it can be changed per
    environment. Uvicorn's loggers are pointed at the same handler to keep a
    single, uniform format.
    """
    global _configured
    if _configured:
        return
    _configured = True

    resolved: str = level.upper()
    logging.config.dictConfig(
        {
            "version": 1,
            # Keep loggers created by libraries (and by tests) working.
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "default": {"format": _LOG_FORMAT, "datefmt": "%Y-%m-%d %H:%M:%S"}
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"level": resolved, "handlers": ["console"]},
            "loggers": {
                # Uvicorn configures its own handlers before importing the app;
                # replace them so its lines carry the request id too.
                "uvicorn": {"level": resolved, "handlers": ["console"], "propagate": False},
                "uvicorn.error": {"level": resolved},
                "uvicorn.access": {
                    "level": resolved,
                    "handlers": ["console"],
                    "propagate": False,
                },
            },
        }
    )


class RequestIdMiddleware:
    """
    Pure ASGI middleware that assigns, propagates and returns a request id.

    Reuses the id sent by Nginx (``$request_id``) when it is well formed and
    generates one otherwise. Unhandled exceptions are rendered by the injected
    global handler so the 500 response carries the same id.
    """

    def __init__(
        self,
        app: ASGIApp,
        error_response_builder: ErrorResponseBuilder | None = None,
    ) -> None:
        self.app = app
        self.error_response_builder = error_response_builder

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str = _request_id_from(scope)
        token = _request_id.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if self.error_response_builder is None:
                raise
            response = await self.error_response_builder(scope, exc)
            headers = [
                (name.encode("latin-1"), value.encode("latin-1"))
                for name, value in response.headers.items()
            ]
            await send_with_request_id(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": headers,
                }
            )
            await send_with_request_id(
                {"type": "http.response.body", "body": response.body}
            )
        finally:
            _request_id.reset(token)


def _request_id_from(scope: Scope) -> str:
    """Return the client-provided request id, or a fresh one if absent/invalid."""
    for name, value in scope["headers"]:
        if name == REQUEST_ID_HEADER.lower().encode():
            candidate: str = value.decode("latin-1").strip()
            if _VALID_REQUEST_ID.fullmatch(candidate):
                return candidate
            break
    return uuid4().hex
