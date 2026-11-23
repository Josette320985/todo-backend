"""
TEST-06: performance regression.

What this module pins down:
- the number of SQL statements of each task endpoint (`count_queries`,
  after OPT-03/04);
- the SQLite PRAGMAs of OPT-05 on every connection, and that the database
  itself now enforces the tasks.owner_id foreign key;
- with the production bcrypt cost, /api/health keeps answering during a
  login (PERF-01). Marked `slow`; the margin is wide on purpose.

Already covered elsewhere and not repeated here:
- EXPLAIN QUERY PLAN of the list uses ix_tasks_owner_id (OPT-01):
  tests/test_opt01_owner_index.py;
- security headers on 200, 401, 404, 422 and 500 (PERF-02):
  tests/test_security_headers.py.

Requests per second are not measured in CI, since they depend on the
machine. That is what scripts/perf/ is for (PERF-07).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.main import create_app
from conftest import TEST_EMAIL, TEST_PASSWORD, QueryLog, TestUser, login
from helpers import create_task, register

TASKS_URL = "/api/v1/tasks/"

# PERF-01: bcrypt at the production cost takes ~250 ms. Health only has to beat
# 100 ms, so scheduler noise on a busy CI runner does not make the test flaky.
PRODUCTION_BCRYPT_ROUNDS = 12
MAX_HEALTH_SECONDS = 0.1


@dataclass(frozen=True)
class Ctx:
    """What a row needs to send its request."""

    client: httpx.AsyncClient
    user: TestUser
    task_id: int


RequestFactory = Callable[[Ctx], Awaitable[httpx.Response]]


async def _list(ctx: Ctx) -> httpx.Response:
    return await ctx.client.get(TASKS_URL, headers=ctx.user.headers)


async def _create(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        TASKS_URL, json={"title": "Nueva"}, headers=ctx.user.headers
    )


async def _update(ctx: Ctx) -> httpx.Response:
    return await ctx.client.put(
        f"{TASKS_URL}{ctx.task_id}",
        json={"title": "Editada", "completed": True},
        headers=ctx.user.headers,
    )


async def _delete(ctx: Ctx) -> httpx.Response:
    return await ctx.client.delete(
        f"{TASKS_URL}{ctx.task_id}", headers=ctx.user.headers
    )


@pytest.mark.parametrize(
    ("make_request", "expected_status", "expected_queries"),
    [
        # user lookup + SELECT of the page (with LIMIT/OFFSET since SEG-H12).
        pytest.param(_list, 200, 2, id="GET"),
        # user lookup + INSERT, plus the per-user cap COUNT that SEG-H12 added
        # after the plan was written (the plan said 2).
        pytest.param(_create, 201, 3, id="POST"),
        # user lookup + SELECT of the owned task + UPDATE; no refresh (OPT-03).
        pytest.param(_update, 200, 3, id="PUT"),
        # user lookup + a single DELETE (OPT-04).
        pytest.param(_delete, 204, 2, id="DELETE"),
    ],
)
async def test_task_endpoint_query_count(
    client: httpx.AsyncClient,
    user: TestUser,
    count_queries: QueryLog,
    make_request: RequestFactory,
    expected_status: int,
    expected_queries: int,
) -> None:
    task = await create_task(client, user.headers, title="Existente")

    count_queries.clear()
    response = await make_request(Ctx(client, user, int(str(task["id"]))))

    assert response.status_code == expected_status, response.text
    assert count_queries.count == expected_queries, list(count_queries)


async def test_sqlite_pragmas_are_set_on_connect(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async with app.state.engine.connect() as conn:
        journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar()
        foreign_keys = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()

    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1  # NORMAL
    assert foreign_keys == 1


async def test_database_enforces_the_task_owner_foreign_key(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """foreign_keys=ON: an orphan task is rejected by SQLite, not only the ORM."""
    async with app.state.engine.connect() as conn:
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            await conn.execute(
                text(
                    "INSERT INTO tasks (title, completed, owner_id) "
                    "VALUES ('huérfana', 0, 999999)"
                )
            )


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.slow
async def test_health_is_not_blocked_by_a_real_login(settings: Settings) -> None:
    """PERF-01 with the real bcrypt, not a patched one (see test_bcrypt_offload)."""
    app = create_app(
        settings.model_copy(update={"BCRYPT_ROUNDS": PRODUCTION_BCRYPT_ROUNDS})
    )
    async with running(app) as client:
        assert (await register(client, TEST_EMAIL, TEST_PASSWORD)).status_code == 201

        # The clock starts with the login: if bcrypt ran in the event loop, the
        # sleep below (which lets the login reach bcrypt) would already last
        # the whole hash, so it must count too.
        started = time.perf_counter()
        login_task = asyncio.create_task(login(client))
        await asyncio.sleep(0.01)
        health = await client.get("/api/health")
        elapsed = time.perf_counter() - started

        assert health.status_code == 200
        assert elapsed < MAX_HEALTH_SECONDS, f"/api/health tardó {elapsed:.3f} s"
        assert not login_task.done(), "the login finished first: nothing was measured"
        assert (await login_task).status_code == 200
