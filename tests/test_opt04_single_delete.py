"""
OPT-04 · DELETE in a single query.

Acceptance criterion: deleting another user's task still answers 404 (the
access control the security report marks as tested must not break).
The query count pins the saving: 3 -> 2 (user lookup + DELETE).
"""

import httpx

from tests.conftest import QueryLog, TestUser

TASKS_URL = "/api/v1/tasks/"


async def create_task(client: httpx.AsyncClient, owner: TestUser) -> str:
    response = await client.post(TASKS_URL, json={"title": "t"}, headers=owner.headers)
    assert response.status_code == 201, response.text
    task_id: str = response.json()["id"]
    return task_id


async def task_ids(client: httpx.AsyncClient, owner: TestUser) -> list[str]:
    listed = (await client.get(TASKS_URL, headers=owner.headers)).json()
    return [task["id"] for task in listed]


async def test_delete_runs_a_single_delete_query(
    client: httpx.AsyncClient, user: TestUser, count_queries: QueryLog
) -> None:
    task_id = await create_task(client, user)

    count_queries.clear()
    response = await client.delete(f"{TASKS_URL}{task_id}", headers=user.headers)

    assert response.status_code == 204, response.text
    # user lookup + DELETE; no SELECT of the task before deleting it.
    assert count_queries.count == 2, list(count_queries)
    assert count_queries[-1].lstrip().upper().startswith("DELETE FROM TASKS")
    assert task_id not in await task_ids(client, user)


async def test_deleting_another_users_task_is_404_and_keeps_it(
    client: httpx.AsyncClient, user: TestUser, other_user: TestUser
) -> None:
    task_id = await create_task(client, user)

    response = await client.delete(
        f"{TASKS_URL}{task_id}", headers=other_user.headers
    )

    assert response.status_code == 404, response.text
    assert task_id in await task_ids(client, user)


async def test_deleting_twice_is_404(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    task_id = await create_task(client, user)

    first = await client.delete(f"{TASKS_URL}{task_id}", headers=user.headers)
    second = await client.delete(f"{TASKS_URL}{task_id}", headers=user.headers)

    assert first.status_code == 204
    assert second.status_code == 404


async def test_delete_only_removes_the_requested_task(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    keep = await create_task(client, user)
    remove = await create_task(client, user)

    await client.delete(f"{TASKS_URL}{remove}", headers=user.headers)

    assert await task_ids(client, user) == [keep]
