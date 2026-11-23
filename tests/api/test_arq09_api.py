"""ARQ-09: coverage for PATCH task updates and the /auth/me profile endpoint."""

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app
from conftest import TestUser
from helpers import create_task

TASKS = "/api/v1/tasks/"
ME = "/api/v1/auth/me"


def task_url(task_id: object) -> str:
    return f"/api/v1/tasks/{task_id}"


async def test_patch_updates_only_sent_fields(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(
        client, auth_headers, title="Original", description="Keep me"
    )

    response = await client.patch(
        task_url(task["id"]), json={"title": "Renamed"}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["description"] == "Keep me"
    assert body["completed"] is False


async def test_put_remains_an_alias_of_patch(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    task = await create_task(client, auth_headers)

    put = await client.put(
        task_url(task["id"]), json={"completed": True}, headers=auth_headers
    )
    patch = await client.patch(
        task_url(task["id"]), json={"title": "Renamed"}, headers=auth_headers
    )

    assert put.status_code == 200
    assert patch.status_code == 200
    body = patch.json()
    assert body["title"] == "Renamed"
    assert body["completed"] is True


async def test_patch_missing_task_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        task_url(999), json={"title": "x"}, headers=auth_headers
    )
    assert response.status_code == 404


async def test_patch_out_of_range_task_id_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        task_url(2**63), json={"title": "x"}, headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"completed": "maybe"},
        {"title": "ok", "start_date": "2026-11-10", "end_date": "2026-11-01"},
    ],
    ids=["null-title", "bad-completed", "end-before-start"],
)
async def test_patch_invalid_body_is_422(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    body: dict[str, object],
) -> None:
    task = await create_task(client, auth_headers)

    response = await client.patch(
        task_url(task["id"]), json=body, headers=auth_headers
    )

    assert response.status_code == 422


async def test_patch_without_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.patch(task_url(1), json={"title": "x"})
    assert response.status_code == 401


async def test_me_returns_public_user(
    client: httpx.AsyncClient, user: TestUser
) -> None:
    response = await client.get(ME, headers=user.headers)

    assert response.status_code == 200
    assert response.json() == {"id": user.id, "email": user.email}


async def test_me_without_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401


def test_put_is_deprecated_and_patch_is_canonical_in_openapi(
    settings: Settings,
) -> None:
    dev_settings: Settings = settings.model_copy(
        update={"ENVIRONMENT": "development"}
    )
    app: FastAPI = create_app(dev_settings)
    operations = app.openapi()["paths"]["/api/v1/tasks/{task_id}"]

    assert operations["put"]["deprecated"] is True
    assert "deprecated" not in operations["patch"]
