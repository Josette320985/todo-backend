"""
Small helpers shared by test modules.

They build on the fixtures in conftest.py (owned by TEST-01) without
changing them, so they can be folded into conftest later.
"""

import httpx

from conftest import login

DEFAULT_PASSWORD: str = "password123"


async def register(
    client: httpx.AsyncClient, email: str, password: str = DEFAULT_PASSWORD
) -> httpx.Response:
    """POST /auth/register and return the raw response."""
    return await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


async def make_user_headers(
    client: httpx.AsyncClient, email: str, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    """Register a user, log in and return its Authorization header."""
    await register(client, email, password)
    token: str = (await login(client, email, password)).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def create_task(
    client: httpx.AsyncClient, headers: dict[str, str], **fields: object
) -> dict[str, object]:
    """Create a task (title defaults to "Task") and return its JSON body."""
    body: dict[str, object] = {"title": "Task", **fields}
    response = await client.post("/api/v1/tasks/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()
    return data
