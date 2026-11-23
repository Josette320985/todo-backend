from collections.abc import AsyncGenerator
from typing import Any, Final

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# Applied to every new SQLite connection (OPT-05):
# - journal_mode=WAL: readers are not blocked while someone writes. It is
#   stored in the database file, the other two are per connection.
# - synchronous=NORMAL: safe with WAL and faster on writes.
# - foreign_keys=ON: SQLite ships with it off, so tasks.owner_id was only
#   enforced by the ORM, not by the database.
SQLITE_PRAGMAS: Final[tuple[str, ...]] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)


def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    """Set SQLITE_PRAGMAS when the pool opens a connection."""
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    """Create the asynchronous database engine for the given URL.

    SQLite connections get SQLITE_PRAGMAS on connect (OPT-05).
    """
    engine = create_async_engine(database_url, echo=False, future=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _configure_sqlite)
    return engine


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
