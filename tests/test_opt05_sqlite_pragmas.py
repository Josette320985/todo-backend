"""
OPT-05: every SQLite connection of the app is configured when it opens.

Acceptance criterion: the benchmark (scripts/perf/bench.py) reports
``journal_mode=wal, foreign_keys=1``. These tests check the same PRAGMAs on the
app's engine, that the database enforces foreign keys, and that migrating an
old database with data still works with foreign keys on.
"""

import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.main import create_app
from app.models.task import Task
from app.models.user import User
from conftest import TestUser, database_path
from tests.test_migrations import LEGACY_SCHEMA

TASKS_URL = "/api/v1/tasks/"

# PRAGMA synchronous reports 0 OFF, 1 NORMAL, 2 FULL, 3 EXTRA.
SYNCHRONOUS_NORMAL = 1


async def pragma(conn: AsyncConnection, name: str) -> object:
    return (await conn.execute(text(f"PRAGMA {name}"))).scalar()


async def test_connections_use_wal_normal_sync_and_foreign_keys(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async with app.state.engine.connect() as conn:
        assert await pragma(conn, "journal_mode") == "wal"
        assert await pragma(conn, "synchronous") == SYNCHRONOUS_NORMAL
        assert await pragma(conn, "foreign_keys") == 1


async def test_every_new_connection_is_configured(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """foreign_keys is per connection: it has to be set on all of them."""
    async with app.state.engine.connect() as first, app.state.engine.connect() as second:
        assert await pragma(first, "foreign_keys") == 1
        assert await pragma(second, "foreign_keys") == 1


async def test_database_rejects_a_task_with_an_unknown_owner(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async with app.state.engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO tasks (title, completed, owner_id) "
                    "VALUES ('orphan', 0, 999999)"
                )
            )


async def test_database_will_not_delete_a_user_that_has_tasks(
    app: FastAPI, client: httpx.AsyncClient, user: TestUser
) -> None:
    """The ORM cascade is not a database rule: raw SQL is refused, not cascaded."""
    created = await client.post(TASKS_URL, headers=user.headers, json={"title": "t"})
    assert created.status_code == 201

    async with app.state.engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": user.id}
            )


async def test_deleting_a_user_through_the_orm_still_deletes_its_tasks(
    app: FastAPI, client: httpx.AsyncClient, user: TestUser
) -> None:
    created = await client.post(TASKS_URL, headers=user.headers, json={"title": "t"})
    assert created.status_code == 201

    async with app.state.session_factory() as session:
        found = (
            await session.execute(
                select(User).where(User.id == user.id).options(selectinload(User.tasks))
            )
        ).scalar_one()
        await session.delete(found)
        await session.commit()

        remaining = (await session.execute(select(Task).where(Task.owner_id == user.id))).all()
    assert remaining == []


async def test_legacy_database_migrates_with_foreign_keys_on(settings: Settings) -> None:
    """
    Migration 0002 rebuilds ``users`` while ``tasks`` points at it. It must not
    fail or lose rows because the app's connections enforce foreign keys, and
    the connections used afterwards must enforce them again.
    """
    path = database_path(settings)
    with sqlite3.connect(path) as legacy:
        legacy.executescript(LEGACY_SCHEMA)

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert app.state.migrated
        async with app.state.engine.connect() as conn:
            assert await pragma(conn, "foreign_keys") == 1
            assert await pragma(conn, "journal_mode") == "wal"
            users = (await conn.execute(text("SELECT email FROM users"))).all()
            tasks = (await conn.execute(text("SELECT title, owner_id FROM tasks"))).all()
    assert users == [("old@example.com",)]
    assert tasks in ([("Tarea vieja", 1)], [("Tarea vieja", "1")])