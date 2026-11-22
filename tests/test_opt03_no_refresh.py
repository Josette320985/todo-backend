"""
OPT-03 · No db.refresh() after saving a task.

Acceptance criterion: the POST response still includes the generated id and
completed=false without the refresh. The query counts pin the saving:
POST 3 -> 2 queries and PUT 4 -> 3 (one of them is the user lookup of the
authentication dependency). Since SEG-H12, POST adds one COUNT for the
per-user cap, before the INSERT.
"""

import httpx

from tests.conftest import QueryLog, TestUser

TASKS_URL = "/api/v1/tasks/"


def selects_on_tasks(log: QueryLog) -> list[str]:
    return [s for s in log if s.lstrip().upper().startswith("SELECT") and "FROM tasks" in s]


async def test_post_returns_generated_values_without_refresh(
    client: httpx.AsyncClient, user: TestUser, count_queries: QueryLog
) -> None:
    count_queries.clear()
    response = await client.post(
        TASKS_URL, json={"title": "Sin refresh"}, headers=user.headers
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["completed"] is False
    assert body["title"] == "Sin refresh"
    assert body["description"] is None

    # user lookup + per-user cap count (SEG-H12) + INSERT. The INSERT is the
    # last statement: no SELECT reads the task back after saving it.
    assert count_queries.count == 3, list(count_queries)
    assert count_queries[-1].lstrip().upper().startswith("INSERT")


async def test_put_returns_updated_values_without_refresh(
    client: httpx.AsyncClient, user: TestUser, count_queries: QueryLog
) -> None:
    created = await client.post(
        TASKS_URL, json={"title": "Antes"}, headers=user.headers
    )
    task_id = created.json()["id"]

    count_queries.clear()
    response = await client.put(
        f"{TASKS_URL}{task_id}",
        json={"title": "Después", "completed": True},
        headers=user.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {**created.json(), "title": "Después", "completed": True}

    # user lookup + SELECT the owned task + UPDATE; no refresh SELECT.
    assert count_queries.count == 3, list(count_queries)
    assert len(selects_on_tasks(count_queries)) == 1


async def test_saved_values_are_really_stored(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    """Without the refresh the response must still match the database."""
    created = (
        await client.post(
            TASKS_URL,
            json={"title": "Persistida", "description": "x"},
            headers=user.headers,
        )
    ).json()

    listed = (await client.get(TASKS_URL, headers=user.headers)).json()

    assert created in listed
