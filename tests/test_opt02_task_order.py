"""
OPT-02 · Deterministic order in GET /tasks.

Acceptance criterion: the list does not change order between reloads.
Order: pending first, then completed; inside each group by end_date (tasks
without end_date last) and finally by id.
"""

import sqlite3
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from tests.conftest import QueryLog, TestUser

TASKS_URL = "/api/v1/tasks/"


async def create(
    client: httpx.AsyncClient, user: TestUser, title: str, **fields: Any
) -> str:
    response = await client.post(
        TASKS_URL, json={"title": title, **fields}, headers=user.headers
    )
    assert response.status_code == 201, response.text
    task_id: str = response.json()["id"]
    return task_id


async def listed_titles(client: httpx.AsyncClient, user: TestUser) -> list[str]:
    response = await client.get(TASKS_URL, headers=user.headers)
    assert response.status_code == 200, response.text
    return [task["title"] for task in response.json()]


async def seed_mixed(client: httpx.AsyncClient, user: TestUser) -> None:
    """Tasks created on purpose in an order that is NOT the expected one."""
    done = await create(client, user, "hecha", end_date="2026-01-01")
    await client.patch(
        f"{TASKS_URL}{done}", json={"completed": True}, headers=user.headers
    )
    await create(client, user, "sin fecha A")
    await create(client, user, "vence tarde", end_date="2026-12-31")
    await create(client, user, "vence pronto", end_date="2026-06-01")
    await create(client, user, "sin fecha B")


async def test_pending_first_then_by_due_date_then_id(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed_mixed(client, user)

    titles = await listed_titles(client, user)
    assert titles[:2] == ["vence pronto", "vence tarde"]
    assert set(titles[2:4]) == {"sin fecha A", "sin fecha B"}
    assert titles[4] == "hecha"


async def test_order_is_stable_between_reloads(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    """Acceptance criterion: same order on every request."""
    await seed_mixed(client, user)
    first = await listed_titles(client, user)

    for _ in range(5):
        assert await listed_titles(client, user) == first


async def test_editing_a_task_moves_it_to_its_place(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    first = await create(client, user, "primera")
    await create(client, user, "segunda")

    await client.patch(
        f"{TASKS_URL}{first}", json={"completed": True}, headers=user.headers
    )

    assert await listed_titles(client, user) == ["segunda", "primera"]


async def test_order_by_still_uses_owner_index(
    client: httpx.AsyncClient,
    user: TestUser,
    settings: Settings,
    count_queries: QueryLog,
) -> None:
    """
    The ORDER BY keeps the lookup on ix_tasks_owner_id (OPT-01); SQLite
    sorts the user's rows in memory. A composite index cannot remove that
    sort because of the `end_date IS NULL` expression, so none is added.
    """
    count_queries.clear()
    await client.get(TASKS_URL, headers=user.headers)
    statement = next(s for s in count_queries if "FROM tasks" in s)

    db_file = Path(settings.DATABASE_URL.split("///", 1)[1])
    with sqlite3.connect(db_file) as conn:
        params = (str(user.id),) + (1,) * (statement.count("?") - 1)  # + LIMIT/OFFSET
        rows = conn.execute(f"EXPLAIN QUERY PLAN {statement}", params).fetchall()
    plan = " | ".join(str(row[-1]) for row in rows)

    assert "ORDER BY" in statement.upper()
    assert "USING INDEX ix_tasks_owner_id" in plan, plan
