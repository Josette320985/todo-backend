from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _configure_sqlite_connection(dbapi_connection: Any, _record: Any) -> None:
    """
    Set the PRAGMAs of a new SQLite connection (OPT-05).

    * ``journal_mode=WAL``: readers are not blocked while someone writes. The
      mode is stored in the database file, so it only changes the first time.
    * ``synchronous=NORMAL``: safe with WAL (a power cut can lose the last
      transactions, never corrupt the file) and faster to write.
    * ``foreign_keys=ON``: SQLite ignores foreign keys unless asked, and the
      setting is per connection. Without it ``cascade`` only worked through the
      ORM; now the database also refuses orphan rows.

    It runs on the raw DBAPI connection, outside SQLAlchemy's execution, so
    these statements do not show up in the query logs and counters.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    """
    Create the asynchronous database engine for the given URL.

    On SQLite every new connection gets the PRAGMAs of
    ``_configure_sqlite_connection``.
    """
    engine: AsyncEngine = create_async_engine(
        database_url, echo=False, future=True
    )
    if engine.sync_engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
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
