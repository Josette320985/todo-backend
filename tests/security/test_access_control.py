"""
TEST-03: users can only reach their own tasks (report section 4,
"Access to other users' tasks").

Covers the mass-assignment side: "owner_id" and "id" sent in the body are
ignored on create and update. The 404 for another user's task is pinned
in tests/api/test_tasks_api.py (TEST-02).
"""

import httpx

from helpers import create_task, make_user_headers

TASKS = "/api/v1/tasks/"


async def test_create_ignores_owner_id_and_id(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    other = await make_user_headers(client, "other@example.com")

    created = await create_task(
        client, auth_headers, title="Mine", owner_id=2, id=12345
    )

    assert created["id"] != 12345
    assert "owner_id" not in created
    mine = (await client.get(TASKS, headers=auth_headers)).json()
    theirs = (await client.get(TASKS, headers=other)).json()
    assert [task["id"] for task in mine] == [created["id"]]
    assert theirs == []


async def test_update_ignores_owner_id_and_id(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    other = await make_user_headers(client, "other@example.com")
    task = await create_task(client, auth_headers, title="Mine")

    response = await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Still mine", "owner_id": 2, "id": 999},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]
    mine = (await client.get(TASKS, headers=auth_headers)).json()
    theirs = (await client.get(TASKS, headers=other)).json()
    assert [t["title"] for t in mine] == ["Still mine"]
    assert theirs == []
