from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str) -> AsyncEngine:
    """Create the asynchronous database engine for the given URL."""
    return create_async_engine(database_url, echo=False, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create a factory of asynchronous sessions bound to the engine.

    Keeps ORM objects accessible after committing a transaction.
    """
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an asynchronous database session for FastAPI dependencies.

    Uses the session factory of the app that received the request (set by
    create_app), so each app instance talks to its own database. The
    session is closed when the dependency finishes.

    Yields:
        AsyncSession: Active asynchronous database session.
    """
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.session_factory
    )
    async with session_factory() as session:
        yield session
