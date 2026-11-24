import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import auth, tasks
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    _request_id,
    _request_id_from,
    configure_logging,
    logger as request_logger,
)
from app.core.metrics import configure_metrics
from app.core.rate_limit import (
    MAX_EMAIL_VALIDATION_ATTEMPTS_PER_WINDOW,
    MAX_LOGIN_ATTEMPTS_PER_EMAIL_PER_WINDOW,
    MAX_LOGIN_ATTEMPTS_PER_WINDOW,
    MAX_REGISTER_ATTEMPTS_PER_WINDOW,
    LoginRateLimiter,
    RateLimiter,
    rate_limit_path,
)
from app.db.migrations import MigrationLock, run_migrations
from app.db.session import create_engine, create_session_factory
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)

logger: Final[logging.Logger] = logging.getLogger("app.health")

# Upper bound for the readiness check (ERR-05). Short enough that a stuck
# database fails the probe instead of piling up requests behind it.
READINESS_TIMEOUT_SECONDS: Final[float] = 2.0

# Failures that mean "the database is not usable right now". Anything else
# (a broken migration script, a bug) still crashes loudly. sqlite3.Error is a
# wait for the migration lock that timed out (BUG-03).
DATABASE_ERRORS: Final = (SQLAlchemyError, OSError, sqlite3.Error)

SECURITY_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-store",
}

UNEXPECTED_ERROR_DETAIL: Final[str] = (
    "Ocurrió un error inesperado. Intenta de nuevo."
)
DATABASE_UNAVAILABLE_DETAIL: Final[str] = (
    "El servicio no está disponible temporalmente. Intenta de nuevo."
)


def _security_headers() -> dict[str, str]:
    """Return a fresh copy so callers can add headers without sharing state."""
    return dict(SECURITY_HEADERS)


async def build_unhandled_error_response(
    scope: Scope, exc: Exception
) -> JSONResponse:
    """Build the public 500 response and log the full traceback (ERR-01)."""
    request = Request(scope)
    request_id: str = _request_id.get()
    if request_id == "-":
        request_id = _request_id_from(scope)
    token = _request_id.set(request_id)
    try:
        request_logger.error(
            "Error no controlado | %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
    finally:
        _request_id.reset(token)

    headers = _security_headers()
    headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=500,
        content={"detail": UNEXPECTED_ERROR_DETAIL, "code": "internal_error"},
        headers=headers,
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Starlette entry point for the shared 500 response."""
    return await build_unhandled_error_response(request.scope, exc)


async def operational_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Build the public 503 response for an unavailable database (ERR-01)."""
    request_id: str = _request_id.get()
    if request_id == "-":
        request_id = _request_id_from(request.scope)
    request_logger.warning(
        "Base de datos no disponible | %s %s | %s",
        request.method,
        request.url.path,
        type(exc).__name__,
    )

    headers = _security_headers()
    headers[REQUEST_ID_HEADER] = request_id
    headers["Retry-After"] = "1"
    return JSONResponse(
        status_code=503,
        content={
            "detail": DATABASE_UNAVAILABLE_DETAIL,
            "code": "service_unavailable",
        },
        headers=headers,
    )


class SecurityHeadersMiddleware:
    """
    Add the HTTP security headers to every response.

    Written as a plain ASGI middleware instead of ``@app.middleware("http")``:
    BaseHTTPMiddleware wraps each request in an extra task and two anyio memory
    streams, which measurably caps throughput on trivial endpoints.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def migrate(engine: AsyncEngine) -> None:
    """Bring the database to the latest Alembic revision (ARQ-03).

    One process at a time (BUG-03): the other workers wait for the lock in a
    thread, so the event loop keeps serving /api/health meanwhile.
    """
    lock = MigrationLock(engine.url)
    await asyncio.to_thread(lock.acquire)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(run_migrations)
    finally:
        lock.release()
    # run_migrations leaves foreign keys off on the connection it used (SQLite).
    # Closing the pooled connections makes the next ones start with the PRAGMAs
    # of the ``connect`` listener (OPT-05), foreign keys included.
    await engine.dispose()


async def health() -> dict[str, str]:
    """
    Liveness: the process is up and serving requests.

    Does not touch the database on purpose, so a database outage does not
    make an orchestrator restart a process that would recover on its own.

    Returns:
        dict[str, str]: A status message indicating that the API is running.
    """
    return {"status": "ok"}


async def check_database(app: FastAPI) -> None:
    """
    Raise if the database cannot serve requests.

    If the migrations failed at startup (the database was unreachable), they
    are retried here first, so the app becomes ready on its own as soon as
    the database is back, without a restart.
    """
    if not app.state.migrated:
        async with app.state.migrate_lock:
            if not app.state.migrated:
                await migrate(app.state.engine)
                app.state.migrated = True
                logger.info("Database migrated after startup; the API is ready")
    async with app.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def ready(request: Request) -> JSONResponse:
    """
    Readiness: the API can reach its database (ERR-05).

    Returns 200 when the database answers ``SELECT 1`` within
    READINESS_TIMEOUT_SECONDS and 503 otherwise. The body never includes the
    error: details go to the log, which is not public.
    """
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await check_database(request.app)
    except TimeoutError:
        logger.warning(
            "Readiness check timed out after %.1f s", READINESS_TIMEOUT_SECONDS
        )
        return JSONResponse({"status": "unavailable"}, status_code=503)
    except DATABASE_ERRORS as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Build a fully configured FastAPI application.

    Every app gets its own settings, database engine and session factory,
    so several apps can live in the same process (for example in tests)
    without sharing configuration or data.

    Args:
        settings (Settings | None): Configuration to use. Defaults to the
            settings loaded from the environment (get_settings()).

    Returns:
        FastAPI: The application, ready to be served by uvicorn.
    """
    app_settings: Settings = settings if settings is not None else get_settings()
    engine = create_engine(app_settings.DATABASE_URL)

    # Configure logging once per process, before the first record is emitted.
    configure_logging(app_settings.LOG_LEVEL)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Migrate the database on startup and close the engine on shutdown.

        The schema is owned by the Alembic migrations (ARQ-03): create_all()
        could create missing tables but never add columns or indexes to
        existing ones.

        If the database cannot be opened, the process still starts (ERR-05):
        /api/health answers 200 and /api/health/ready answers 503, retrying
        the migrations, until the database is reachable. Crashing instead
        would leave nothing to report the problem.
        """
        try:
            await migrate(engine)
            app.state.migrated = True
        except DATABASE_ERRORS:
            logger.exception(
                "Database unavailable at startup; /api/health/ready answers "
                "503 until it is reachable"
            )
        yield
        for name in ("login_limiter", "register_limiter", "email_validation_limiter"):
            getattr(app.state, name).close()
        await engine.dispose()

    # API docs only in development (SEG-H07). Allow-list instead of
    # `!= "production"`: "Production", a typo or any other value keeps the
    # schema, Swagger and ReDoc closed instead of exposing them.
    docs_enabled: bool = app_settings.ENVIRONMENT.strip().lower() == "development"

    app = FastAPI(
        title="To-Do API — Equipo 1",
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url="/api/redoc" if docs_enabled else None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )

    # Per-app state read by the dependencies (get_db, get_settings).
    app.state.settings = app_settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.migrated = False
    app.state.migrate_lock = asyncio.Lock()
    # One limiter per endpoint (ARQ-05). Their counters live in a file next to
    # the database, so every uvicorn worker of the deployment shares them
    # (BUG-02) while apps with different databases (tests) never do. Tests may
    # replace them, for example to inject a fake clock.
    limits_path: str = rate_limit_path(app_settings.DATABASE_URL)

    def limiter(name: str, max_attempts: int) -> RateLimiter:
        return RateLimiter(max_attempts=max_attempts, path=limits_path, name=name)

    app.state.login_limiter = LoginRateLimiter(
        per_ip=limiter("login_ip", MAX_LOGIN_ATTEMPTS_PER_WINDOW),
        per_pair=limiter("login_pair", MAX_LOGIN_ATTEMPTS_PER_EMAIL_PER_WINDOW),
    )
    app.state.register_limiter = limiter("register", MAX_REGISTER_ATTEMPTS_PER_WINDOW)
    app.state.email_validation_limiter = limiter(
        "email_validation", MAX_EMAIL_VALIDATION_ATTEMPTS_PER_WINDOW
    )
    app.dependency_overrides[get_settings] = lambda: app_settings
    register_exception_handlers(app)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(OperationalError, operational_error_handler)

    # Configure Cross-Origin Resource Sharing (CORS) with explicit methods/headers.
    # Credentials are disabled: auth uses a Bearer header, not cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Assign, propagate and return the X-Request-ID of every request (ERR-04).
    app.add_middleware(
        RequestIdMiddleware, error_response_builder=build_unhandled_error_response
    )

    # Register Prometheus HTTP metrics and /metrics before SecurityHeadersMiddleware
    # so SecurityHeadersMiddleware remains the outermost ASGI layer.
    if app_settings.METRICS_ENABLED:
        configure_metrics(app)

    # Added last so it is the outermost middleware: the headers also reach the
    # responses built by the other middlewares. The global 500 handler lives
    # outside this stack, so it adds them itself (PERF-02, ERR-01).
    app.add_middleware(SecurityHeadersMiddleware)

    # Register authentication and task management routes.
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route("/api/health/ready", ready, methods=["GET"])

    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """
    Provide the uvicorn application (app.main:app) on first access.

    The instance is created lazily, so importing this module (for example
    to call create_app() in tests) does not require SECRET_KEY or a .env
    file. uvicorn resolves "app.main:app" with getattr(), which lands here.
    """
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
