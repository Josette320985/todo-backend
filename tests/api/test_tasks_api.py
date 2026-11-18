"""
TEST-02: characterization of the task endpoints.

Pins the current behaviour of the task CRUD (create, list, partial update,
toggle, delete), ownership (another user gets 404), authentication (401)
and validation (422) before the refactor (ARQ-02, ARQ-04). The refactor
must keep these tests green without editing them. When a behaviour change
is intentional, update the test in the same PR that changes it.
"""

import httpx
import pytest

from helpers import create_task, make_user_headers

TASKS = "/api/v1/tasks/"


def task_url(task_id: object) -> str:
    return f"/api/v1/tasks/{task_id}"


# --- Create -----------------------------------------------------------------


async def test_create_returns_201_with_defaults(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        TASKS, json={"title": "Buy milk"}, headers=auth_headers
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id", "title", "description", "completed", "start_date", "end_date"
    }
    assert body["title"] == "Buy milk"
    assert body["description"] is None
    assert body["completed"] is False
    assert body["start_date"] is None
    assert body["end_date"] is None


async def test_create_with_all_fields(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = await create_task(
        client,
        auth_headers,
        title="Report",
        description="Quarterly",
        start_date="2026-11-01",
        end_date="2026-11-30",
    )

    assert body["description"] == "Quarterly"
    assert body["start_date"] == "2026-11-01"
    assert body["end_date"] == "2026-11-30"


async def test_create_strips_title(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = await create_task(client, auth_headers, title="  Padded  ")
    assert body["title"] == "Padded"


# --- List -------------------------------------------------------------------


async def test_list_is_empty_for_new_user(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(TASKS, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_list_returns_created_tasks(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await create_task(client, auth_headers, title="First")
    second = await create_task(client, auth_headers, title="Second")

    response = await client.get(TASKS, headers=auth_headers)

    assert response.status_code == 200
    listed_ids = sorted(task["id"] for task in response.json())
    assert listed_ids == sorted([first["id"], second["id"]])


# --- Update -----------------------------------------------------------------


async def test_partial_update_changes_only_sent_fields(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(
        client, auth_headers, title="Original", description="Keep me"
    )

    response = await client.put(
        task_url(task["id"]), json={"title": "Renamed"}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["description"] == "Keep me"
    assert body["completed"] is False


async def test_toggle_completed(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers)

    done = await client.put(
        task_url(task["id"]), json={"completed": True}, headers=auth_headers
    )
    undone = await client.put(
        task_url(task["id"]), json={"completed": False}, headers=auth_headers
    )

    assert done.json()["completed"] is True
    assert undone.json()["completed"] is False


async def test_update_can_clear_description(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers, description="Temp")

    response = await client.put(
        task_url(task["id"]), json={"description": None}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["description"] is None


async def test_update_is_persisted(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers)
    await client.put(
        task_url(task["id"]), json={"completed": True}, headers=auth_headers
    )

    listed = (await client.get(TASKS, headers=auth_headers)).json()

    assert listed[0]["completed"] is True


async def test_update_end_before_stored_start_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers, start_date="2026-11-10")

    response = await client.put(
        task_url(task["id"]),
        json={"end_date": "2026-11-01"},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_update_missing_task_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        task_url(999), json={"title": "x"}, headers=auth_headers
    )
    assert response.status_code == 404


# --- Delete -----------------------------------------------------------------


async def test_delete_returns_204_and_removes_task(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers)

    response = await client.delete(task_url(task["id"]), headers=auth_headers)

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(TASKS, headers=auth_headers)).json() == []


async def test_delete_twice_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers)
    await client.delete(task_url(task["id"]), headers=auth_headers)

    response = await client.delete(task_url(task["id"]), headers=auth_headers)

    assert response.status_code == 404


# --- Ownership --------------------------------------------------------------


async def test_other_user_cannot_see_update_or_delete(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers, title="Private")
    other = await make_user_headers(client, "other@example.com")

    listed = await client.get(TASKS, headers=other)
    updated = await client.put(
        task_url(task["id"]), json={"title": "Hacked"}, headers=other
    )
    deleted = await client.delete(task_url(task["id"]), headers=other)

    assert listed.json() == []
    assert updated.status_code == 404
    assert deleted.status_code == 404
    # The owner's task is untouched.
    own = (await client.get(TASKS, headers=auth_headers)).json()
    assert own[0]["title"] == "Private"


# --- Authentication ---------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", TASKS),
        ("POST", TASKS),
        ("PUT", task_url(1)),
        ("DELETE", task_url(1)),
    ],
)
async def test_task_endpoints_without_token_are_401(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, json={"title": "x"})
    assert response.status_code == 401


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "ok", "description": "x" * 1001},
        {"title": "ok", "start_date": "2026-11-10", "end_date": "2026-11-01"},
        {"title": "ok", "start_date": "not-a-date"},
        {"title": None},
    ],
    ids=[
        "missing-title",
        "empty-title",
        "blank-title",
        "long-title",
        "long-description",
        "end-before-start",
        "bad-date",
        "null-title",
    ],
)
async def test_create_invalid_body_is_422(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    body: dict[str, object],
) -> None:
    response = await client.post(TASKS, json=body, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"completed": None},
        {"title": ""},
        {"completed": "maybe"},
    ],
    ids=["null-title", "null-completed", "empty-title", "bad-completed"],
)
async def test_update_invalid_body_is_422(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    body: dict[str, object],
) -> None:
    task = await create_task(client, auth_headers)

    response = await client.put(
        task_url(task["id"]), json=body, headers=auth_headers
    )

    assert response.status_code == 422


async def test_non_integer_task_id_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        task_url("abc"), json={"title": "x"}, headers=auth_headers
    )
    assert response.status_code == 422
