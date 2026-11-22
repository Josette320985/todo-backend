"""
TEST-03 / SEG-H06: an oversized task id must not reach SQLite.

SQLite stores INTEGER as a signed 64-bit value. A larger id makes the driver
raise OverflowError, which used to escape as a 500. The path parameter is now
bounded, so FastAPI rejects it with 422 before the handler runs.
"""

import httpx
import pytest

from helpers import create_task

TASKS = "/api/v1/tasks/"
SQLITE_MAX_INTEGER = 2**63 - 1


def task_url(task_id: object) -> str:
    return f"{TASKS}{task_id}"


@pytest.mark.parametrize("task_id", [99999999999999999999, 2**63])
async def test_put_out_of_range_task_id_is_422(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    task_id: int,
) -> None:
    response = await client.put(
        task_url(task_id), json={"title": "x"}, headers=auth_headers
    )

    assert response.status_code == 422


async def test_delete_out_of_range_task_id_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.delete(
        task_url(99999999999999999999), headers=auth_headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("task_id", [0, -1])
async def test_non_positive_task_id_is_422(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    task_id: int,
) -> None:
    response = await client.put(
        task_url(task_id), json={"title": "x"}, headers=auth_headers
    )

    assert response.status_code == 422


async def test_max_sqlite_id_is_404_not_500(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        task_url(SQLITE_MAX_INTEGER), json={"title": "x"}, headers=auth_headers
    )

    assert response.status_code == 404


async def test_valid_task_id_still_works(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers, title="Control")

    response = await client.put(
        task_url(task["id"]), json={"completed": True}, headers=auth_headers
    )

    assert response.status_code == 200
