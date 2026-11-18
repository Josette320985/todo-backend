from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import os
from typing import Final

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, tasks
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)

# Disable API docs in production to reduce enumeration surface.
_ENV: str = os.getenv("ENVIRONMENT", settings.ENVIRONMENT)
_docs_url: str | None = None if _ENV == "production" else "/api/docs"
_redoc_url: str | None = None if _ENV == "production" else "/api/redoc"
_openapi_url: str | None = None if _ENV == "production" else "/api/openapi.json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manage application startup and shutdown.

    Creates database tables defined in SQLAlchemy metadata
    if they do not already exist.
    """
    # Initialize database tables when the application starts.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


# Create the FastAPI application and configure API documentation.
app: Final[FastAPI] = FastAPI(
    title="To-Do API — Equipo 1",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Configure Cross-Origin Resource Sharing (CORS) with explicit methods/headers.
# Credentials are disabled: auth uses a Bearer header, not cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
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


# Register authentication and task management routes.
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """
    Check whether the API service is responding.

    Returns:
        dict[str, str]: A status message indicating that the API is running.
    """
    return {"status": "ok"}
