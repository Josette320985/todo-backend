"""Sort options of GET /tasks (OPT-02 follow-up).

Without sort_by the OPT-02 order applies (fallback). With sort_by the fields
are applied in sequence, NULL dates always go last and the id breaks ties.
"""

from typing import Any

import httpx

from tests.conftest import TestUser

TASKS_URL = "/api/v1/tasks/"

# What the frontend sends: the same fields as the backend fallback.
PENDING_FIRST = ["completed", "end_date", "id"]


async def create(
    client: httpx.AsyncClient, user: TestUser, title: str, **fields: Any
) -> str:
    response = await client.post(
        TASKS_URL, json={"title": title, **fields}, headers=user.headers
    )
    assert response.status_code == 201, response.text
    task_id: str = response.json()["id"]
    return task_id


async def titles(
    client: httpx.AsyncClient, user: TestUser, **params: Any
) -> list[str]:
    response = await client.get(TASKS_URL, params=params, headers=user.headers)
    assert response.status_code == 200, response.text
    return [task["title"] for task in response.json()]


async def seed(client: httpx.AsyncClient, user: TestUser) -> None:
    """Ids 1..4, created in an order that is NOT the expected one."""
    done = await create(client, user, "Hecha", end_date="2026-01-01")
    await client.patch(
        f"{TASKS_URL}{done}", json={"completed": True}, headers=user.headers
    )
    await create(client, user, "sin fecha")
    await create(client, user, "Tarde", end_date="2026-12-31")
    await create(client, user, "pronto", end_date="2026-06-01")


async def test_no_params_uses_opt02_fallback(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    expected = ["pronto", "Tarde", "sin fecha", "Hecha"]
    assert await titles(client, user) == expected
    # `order` alone does not change the fallback.
    assert await titles(client, user, order="desc") == expected


async def test_explicit_pending_first_equals_the_fallback(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    assert await titles(client, user, sort_by=PENDING_FIRST, order="asc") == (
        await titles(client, user)
    )
    assert await titles(client, user, sort_by=PENDING_FIRST) == [
        "pronto",
        "Tarde",
        "sin fecha",
        "Hecha",
    ]


async def test_sort_by_title_is_case_insensitive(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    assert await titles(client, user, sort_by="title") == [
        "Hecha",
        "pronto",
        "sin fecha",
        "Tarde",
    ]
    assert await titles(client, user, sort_by="title", order="desc") == [
        "Tarde",
        "sin fecha",
        "pronto",
        "Hecha",
    ]


async def test_sort_by_end_date_keeps_undated_last_in_both_directions(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    # A single field ignores the completed flag: "Hecha" is not pushed down.
    assert await titles(client, user, sort_by="end_date") == [
        "Hecha",
        "pronto",
        "Tarde",
        "sin fecha",
    ]
    assert await titles(client, user, sort_by="end_date", order="desc") == [
        "Tarde",
        "pronto",
        "Hecha",
        "sin fecha",
    ]


async def test_several_fields_apply_in_sequence(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    # Completed first (desc), then newest id first.
    assert await titles(
        client, user, sort_by=["completed", "id"], order="desc"
    ) == ["Hecha", "pronto", "Tarde", "sin fecha"]


async def test_sort_by_id_desc_is_newest_first(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    assert await titles(client, user, sort_by="id", order="desc") == [
        "pronto",
        "Tarde",
        "sin fecha",
        "Hecha",
    ]


async def test_sort_combines_with_filter_and_pagination(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    await seed(client, user)

    assert await titles(
        client, user, sort_by="title", completed="false", limit="2", offset="1"
    ) == ["sin fecha", "Tarde"]


async def test_invalid_sort_values_are_rejected(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    too_many = ["completed", "end_date", "start_date", "title", "id", "id"]
    for params in (
        {"sort_by": "default"},
        {"sort_by": "owner_id"},
        {"sort_by": "title; DROP TABLE tasks"},
        {"sort_by": too_many},
        {"order": "sideways"},
    ):
        response = await client.get(TASKS_URL, params=params, headers=user.headers)
        assert response.status_code == 422, params