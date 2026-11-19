from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Connection, inspect, text

from app.api.v1 import auth, tasks
from app.core.config import Settings, get_settings
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)


def add_token_version_column(conn: Connection) -> None:
    """Add users.token_version to databases created before it existed."""
    columns = {col["name"] for col in inspect(conn).get_columns("users")}
    if "token_version" not in columns:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
        ))


async def add_security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach HTTP security headers to every API response."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


async def health() -> dict[str, str]:
    """
    Check whether the API service is responding.

    Returns:
        dict[str, str]: A status message indicating that the API is running.
    """
    return {"status": "ok"}


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
        """Create missing tables on startup and close the engine on shutdown."""
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(add_token_version_column)
        yield
        await engine.dispose()

    # Disable API docs in production to reduce enumeration surface.
    docs_enabled: bool = app_settings.ENVIRONMENT != "production"

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
    app.dependency_overrides[get_settings] = lambda: app_settings

    # Configure Cross-Origin Resource Sharing (CORS) with explicit methods/headers.
    # Credentials are disabled: auth uses a Bearer header, not cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.middleware("http")(add_security_headers)

    # Assign, propagate and return the X-Request-ID of every request. Added last
    # so it wraps the other middlewares: the id reaches the responses they build
    # and the 500 produced by the error path (ERR-04).
    app.add_middleware(RequestIdMiddleware)

    # Register authentication and task management routes.
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.add_api_route("/api/health", health, methods=["GET"])

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
