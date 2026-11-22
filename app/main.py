import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import auth, tasks
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.migrations import run_migrations
from app.db.session import create_engine, create_session_factory
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)

logger: Final[logging.Logger] = logging.getLogger("app.health")

# Upper bound for the readiness check (ERR-05). Short enough that a stuck
# database fails the probe instead of piling up requests behind it.
READINESS_TIMEOUT_SECONDS: Final[float] = 2.0

# Failures that mean "the database is not usable right now". Anything else
# (a broken migration script, a bug) still crashes loudly.
DATABASE_ERRORS: Final = (SQLAlchemyError, OSError)


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
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def migrate(engine: AsyncEngine) -> None:
    """Bring the database to the latest Alembic revision (ARQ-03)."""
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)


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
    app.dependency_overrides[get_settings] = lambda: app_settings
    register_exception_handlers(app)

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
    app.add_middleware(RequestIdMiddleware)

    # Added last so it is the outermost middleware: the headers also reach the
    # responses built by the other middlewares, including the 500 of the error
    # path (PERF-02).
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
