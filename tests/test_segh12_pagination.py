"""
SEG-H12 · Pagination and per-user task cap.

Acceptance criteria:
  * GET /api/v1/tasks/?limit=1000000 answers 422 (or is cut to the maximum).
  * Creating more tasks than the cap answers 4xx.
Also: limit/offset pages follow the OPT-02 order without gaps or repeats,
and ?completed= filters by status.
"""

import httpx
import pytest

from app.services import task_service
from tests.conftest import TestUser

TASKS_URL = "/api/v1/tasks/"


async def create(client: httpx.AsyncClient, user: TestUser, title: str) -> int:
    response = await client.post(TASKS_URL, json={"title": title}, headers=user.headers)
    assert response.status_code == 201, response.text
    task_id: int = response.json()["id"]
    return task_id


async def page(
    client: httpx.AsyncClient, user: TestUser, **params: object
) -> httpx.Response:
    return await client.get(TASKS_URL, params=params, headers=user.headers)


async def test_huge_limit_is_rejected(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    response = await page(client, user, limit=1_000_000)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": -1}, {"offset": -1}, {"offset": 10**12}],
)
async def test_invalid_page_parameters_are_422(
    client: httpx.AsyncClient, user: TestUser, params: dict[str, int]
) -> None:
    response = await page(client, user, **params)

    assert response.status_code == 422, response.text


async def test_without_parameters_returns_every_task(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    """The current frontend sends no parameters and must keep seeing all tasks."""
    for i in range(3):
        await create(client, user, f"t{i}")

    response = await page(client, user)

    assert response.status_code == 200
    assert [t["title"] for t in response.json()] == ["t0", "t1", "t2"]


async def test_pages_cover_the_list_without_gaps_or_repeats(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    ids = [await create(client, user, f"t{i}") for i in range(5)]

    pages = [
        [t["id"] for t in (await page(client, user, limit=2, offset=off)).json()]
        for off in (0, 2, 4, 6)
    ]

    assert pages == [ids[0:2], ids[2:4], ids[4:5], []]


async def test_completed_filter(client: httpx.AsyncClient, user: TestUser) -> None:
    pending = await create(client, user, "pendiente")
    done = await create(client, user, "hecha")
    await client.patch(
        f"{TASKS_URL}{done}", json={"completed": True}, headers=user.headers
    )

    only_done = await page(client, user, completed="true")
    only_pending = await page(client, user, completed="false")

    assert [t["id"] for t in only_done.json()] == [done]
    assert [t["id"] for t in only_pending.json()] == [pending]


async def test_pagination_never_shows_other_users_tasks(
    client: httpx.AsyncClient, user: TestUser, other_user: TestUser
) -> None:
    await create(client, other_user, "ajena")

    response = await page(client, user, limit=10, offset=0)

    assert response.json() == []


async def test_task_cap_per_user(
    client: httpx.AsyncClient,
    user: TestUser,
    other_user: TestUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating more tasks than the cap answers 409; other users are unaffected."""
    monkeypatch.setattr(task_service, "MAX_TASKS_PER_USER", 3)
    for i in range(3):
        await create(client, user, f"t{i}")

    rejected = await client.post(
        TASKS_URL, json={"title": "una más"}, headers=user.headers
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "task_limit_reached"
    assert len((await page(client, user)).json()) == 3
    # The cap is per user: someone else can still create tasks.
    await create(client, other_user, "de otro")


async def test_deleting_frees_room_under_the_cap(
    client: httpx.AsyncClient, user: TestUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_service, "MAX_TASKS_PER_USER", 1)
    first = await create(client, user, "única")

    blocked = await client.post(TASKS_URL, json={"title": "x"}, headers=user.headers)
    await client.delete(f"{TASKS_URL}{first}", headers=user.headers)
    allowed = await client.post(TASKS_URL, json={"title": "x"}, headers=user.headers)

    assert blocked.status_code == 409
    assert allowed.status_code == 201
