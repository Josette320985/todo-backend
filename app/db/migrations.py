"""
Run the Alembic migrations from the application (ARQ-03).

create_app()'s lifespan calls run_migrations() through
AsyncConnection.run_sync(), so every start of the container (and every test
app) brings its database to the latest revision before serving requests.

Databases created before ARQ-03 have the tables but no alembic_version
table. They are stamped at the initial revision ("0001", the schema Equipo 1
delivered) and then upgraded, so no table is recreated and no data is lost.
"""

import sqlite3
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, inspect

from app.db.session import sqlite_sibling_path

# Repository root: app/db/migrations.py -> parents[2].
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ALEMBIC_INI: Path = PROJECT_ROOT / "alembic.ini"

# Revision that matches the schema create_all() used to build.
BASELINE_REVISION: str = "0001"

# How long a process waits for another one that is migrating (BUG-03). Long
# enough for a batch migration of a large table; past it the wait fails like
# an unreachable database and /api/health/ready retries (ERR-05).
MIGRATION_LOCK_TIMEOUT_SECONDS: Final[float] = 60.0


class MigrationLock:
    """
    Only one process at a time runs the migrations of a database (BUG-03).

    With several uvicorn workers (PERF-03) every worker migrates on startup.
    Without this, they all saw "no alembic_version" at once and raced: "table
    alembic_version already exists", "database is locked", and workers that
    reported the database as unavailable. With it, the first one migrates and
    the others wait, then find the database at head and do nothing.

    The lock is a ``BEGIN EXCLUSIVE`` on a file next to the database
    (``todo.migrate.lock``): it works on every OS, needs no dependency, and the
    OS releases it if the process dies while holding it. An in-memory or
    non-SQLite database has no file to share and gets no lock.
    """

    def __init__(self, database_url: str | URL, timeout: float | None = None) -> None:
        self.path: Final[Path | None] = sqlite_sibling_path(database_url, "migrate.lock")
        # Read on use, not at import, so tests can shorten the module constant.
        self._timeout: Final[float | None] = timeout
        self._connection: sqlite3.Connection | None = None

    def acquire(self) -> None:
        """Block until no other process holds the lock, then take it."""
        if self.path is None:
            return
        # Not in a `with`: the connection must stay open while the lock is held.
        # check_same_thread=False: migrate() takes the lock in a worker thread
        # (asyncio.to_thread) and releases it from the event loop.
        connection = sqlite3.connect(
            self.path,
            timeout=(
                MIGRATION_LOCK_TIMEOUT_SECONDS if self._timeout is None else self._timeout
            ),
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def release(self) -> None:
        """Release the lock: closing the connection ends its transaction."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def alembic_config(connection: Connection) -> Config:
    """Alembic config that reuses the given connection instead of a new engine."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


def run_migrations(connection: Connection) -> None:
    """
    Stamp pre-Alembic databases, then upgrade to the latest revision.

    On SQLite this turns foreign key enforcement off for the connection
    (OPT-05), as SQLite's own procedure for altering tables requires: the batch
    migrations copy a table, drop the original and rename the copy, and with
    enforcement on, ``DROP TABLE users`` fails while ``tasks`` still points at
    it. The setting cannot be restored from here, because it is ignored inside
    a transaction: the caller must not reuse the connection afterwards.
    ``main.migrate`` discards the pool, so the next connections get the
    PRAGMAs again from the ``connect`` listener of ``db.session``.
    """
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
