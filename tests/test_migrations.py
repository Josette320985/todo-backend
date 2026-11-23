"""
Alembic migrations (ARQ-03).

Acceptance criterion: a copy of a pre-Alembic data/todo.db is stamped and
upgraded on startup; the index is created and no data is lost.
"""

import sqlite3
from pathlib import Path

import httpx
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import Connection, create_engine, inspect

from app.core.config import Settings
from app.db.base import Base
from app.db.migrations import PROJECT_ROOT
from app.main import create_app
from tests.conftest import TestUser

HEAD: str = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_current_head() or ""

# Schema exactly as create_all() built it before SEG-H10 and ARQ-03.
LEGACY_SCHEMA: str = """
CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE TABLE tasks (
    id INTEGER NOT NULL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description VARCHAR(1000),
    completed BOOLEAN NOT NULL,
    start_date DATE,
    end_date DATE,
    owner_id INTEGER NOT NULL REFERENCES users (id)
);
INSERT INTO users (id, email, hashed_password) VALUES (1, 'old@example.com', 'x');
INSERT INTO tasks (id, title, description, completed, owner_id)
    VALUES (1, 'Tarea vieja', 'antes de Alembic', 0, 1);
"""


def db_path(settings: Settings) -> Path:
    return Path(settings.DATABASE_URL.split("///", 1)[1])


def sync_inspect(path: Path) -> tuple[set[str], dict[str, set[str]], str | None]:
    """Tables, index names per table and Alembic revision of a database."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        indexes = {t: {i["name"] or "" for i in insp.get_indexes(t)} for t in tables}
        revision = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()
    return tables, indexes, revision


async def start(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pass


async def test_new_database_is_created_by_migrations(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    tables, indexes, revision = sync_inspect(db_path(settings))

    assert {"users", "tasks", "alembic_version"} <= tables
    assert "ix_tasks_owner_id" in indexes["tasks"]
    assert revision == HEAD


async def test_legacy_database_keeps_its_data(settings: Settings) -> None:
    path = db_path(settings)
    with sqlite3.connect(path) as conn:
        conn.executescript(LEGACY_SCHEMA)

    await start(create_app(settings))

    tables, indexes, revision = sync_inspect(path)
    assert revision == HEAD
    assert "ix_tasks_owner_id" in indexes["tasks"]
    with sqlite3.connect(path) as conn:
        user = conn.execute(
            "SELECT email, token_version FROM users WHERE id = 1"
        ).fetchone()
        task = conn.execute("SELECT title, owner_id FROM tasks WHERE id = 1").fetchone()
    assert user == ("old@example.com", 0)
    assert task == ("Tarea vieja", 1)


async def test_database_patched_by_seg_h10_is_upgraded(settings: Settings) -> None:
    """DBs that already got token_version from the old startup patch."""
    path = db_path(settings)
    with sqlite3.connect(path) as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
        )

    await start(create_app(settings))

    _, indexes, revision = sync_inspect(path)
    assert revision == HEAD
    assert "ix_tasks_owner_id" in indexes["tasks"]


async def test_restart_is_a_no_op(settings: Settings) -> None:
    await start(create_app(settings))
    await start(create_app(settings))

    assert sync_inspect(db_path(settings))[2] == HEAD


async def test_api_works_on_migrated_schema(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    """Smoke check: the migrated schema serves the API as before."""
    created = await client.post(
        "/api/v1/tasks/", json={"title": "Después de migrar"}, headers=user.headers
    )
    assert created.status_code == 201, created.text


async def test_models_match_migrations(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    """A model change without its migration fails here (and in the CI)."""
    engine = create_engine(f"sqlite:///{db_path(settings).as_posix()}")
    with engine.connect() as conn:
        diff = _diff(conn)
    engine.dispose()
    assert diff == [], f"Models and migrations differ; add a migration: {diff}"


def _diff(conn: Connection) -> list[object]:
    context = MigrationContext.configure(conn, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))
