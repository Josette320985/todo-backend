from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, tasks
from app.db.base import Base
from app.db.session import engine
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app = FastAPI(
    title="To-Do API — Equipo 1",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Configure Cross-Origin Resource Sharing (CORS).
# Allow requests from the specified frontend development origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register authentication and task management routes.
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")


@app.get("/api/health")
async def health():
    """
    Check whether the API service is responding.

    Returns:
        dict: A status message indicating that the API is running.
    """
    return {"status": "ok"}
