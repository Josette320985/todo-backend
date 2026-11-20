"""
Alembic environment (ARQ-03).

Two ways in:
  * From the app (app/db/migrations.py): a live connection arrives in
    config.attributes["connection"] and is reused, so the migrations run on
    the same engine and database as the app (and the tests).
  * From the CLI (`alembic upgrade head`): a synchronous engine is built from
    DATABASE_URL. The async driver is swapped for the sync one because the
    CLI does not need an event loop.

render_as_batch=True: SQLite cannot ALTER most columns, so Alembic copies
the table, applies the change and swaps it back.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from app.db.base import Base
from app.models.task import Task  # noqa: F401  (registers the model)
from app.models.user import User  # noqa: F401  (registers the model)

config = context.config
target_metadata = Base.metadata

DEFAULT_DATABASE_URL = "sqlite:///./data/todo.db"


def sync_url(url: str) -> str:
    """sqlite+aiosqlite:///x.db -> sqlite:///x.db (the CLI runs synchronously)."""
    return url.replace("+aiosqlite", "")


def run_with(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(
        url=sync_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)),
        target_metadata=target_metadata,
        render_as_batch=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection: Connection | None = config.attributes.get("connection")
    if connection is not None:
        # Called from the app: keep the app's logging configuration.
        run_with(connection)
        return

    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
    url = sync_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        run_with(conn)
        conn.commit()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
