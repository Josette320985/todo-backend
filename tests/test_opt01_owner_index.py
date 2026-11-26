"""
OPT-01 · Index on tasks.owner_id.

Acceptance criterion: EXPLAIN QUERY PLAN of the real GET /tasks query shows
"SEARCH tasks USING INDEX ix_tasks_owner_id" instead of a full table scan.
The index itself comes from migration 0003 (ARQ-03).
"""

import sqlite3
from pathlib import Path

import httpx

from app.core.config import Settings
from tests.conftest import QueryLog, TestUser


async def list_tasks_query(
    client: httpx.AsyncClient, user: TestUser, count_queries: QueryLog
) -> str:
    """The SQL statement GET /tasks really runs against the tasks table."""
    count_queries.clear()
    response = await client.get("/api/v1/tasks/", headers=user.headers)
    assert response.status_code == 200, response.text
    statements = [s for s in count_queries if "FROM tasks" in s]
    assert len(statements) == 1, statements
    return statements[0]


def query_plan(settings: Settings, statement: str, owner_id: object) -> str:
    db_file = Path(settings.DATABASE_URL.split("///", 1)[1])
    with sqlite3.connect(db_file) as conn:
        # owner_id first; any later placeholder (LIMIT/OFFSET since SEG-H12)
        # gets a dummy value, which does not change the plan.
        params = (str(owner_id),) + (1,) * (statement.count("?") - 1)
        rows = conn.execute(f"EXPLAIN QUERY PLAN {statement}", params).fetchall()
    return " | ".join(str(row[-1]) for row in rows)


async def test_list_tasks_uses_owner_index(
    client: httpx.AsyncClient,
    user: TestUser,
    settings: Settings,
    count_queries: QueryLog,
) -> None:
    statement = await list_tasks_query(client, user, count_queries)

    plan = query_plan(settings, statement, user.id)

    assert "USING INDEX ix_tasks_owner_id" in plan, plan
    assert "SCAN tasks" not in plan, plan


async def test_without_index_the_query_scans_the_table(
    client: httpx.AsyncClient,
    user: TestUser,
    settings: Settings,
    count_queries: QueryLog,
) -> None:
    """'Before' of OPT-01: the same query without the index reads every row."""
    statement = await list_tasks_query(client, user, count_queries)
    db_file = Path(settings.DATABASE_URL.split("///", 1)[1])
    with sqlite3.connect(db_file) as conn:
        conn.execute("DROP INDEX ix_tasks_owner_id")

    plan = query_plan(settings, statement, user.id)

    assert "SCAN tasks" in plan, plan
