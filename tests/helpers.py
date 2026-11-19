"""
Small request helpers shared by test modules.

Users come from the conftest.py fixtures (make_user, user, other_user).
"""

import httpx

DEFAULT_PASSWORD: str = "password123"


async def register(
    client: httpx.AsyncClient, email: str, password: str = DEFAULT_PASSWORD
) -> httpx.Response:
    """POST /auth/register and return the raw response."""
    return await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


async def create_task(
    client: httpx.AsyncClient, headers: dict[str, str], **fields: object
) -> dict[str, object]:
    """Create a task (title defaults to "Task") and return its JSON body."""
    body: dict[str, object] = {"title": "Task", **fields}
    response = await client.post("/api/v1/tasks/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()
    return data
