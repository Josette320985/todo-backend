"""
TEST-03: injection payloads are stored as plain data (report section 4,
"SQL injection" and "XSS").

The backend must store and return these strings byte for byte, without
executing them and without breaking the database. Rendering them as text
in the browser is the frontend's job (TEST-08, TEST-09).
"""

import httpx
import pytest

from conftest import login
from helpers import create_task

TASKS = "/api/v1/tasks/"

SQL_PAYLOAD = "x' OR 1=1; DROP TABLE tasks;--"

XSS_PAYLOADS = [
    "<img src=x onerror=alert(1)>",
    "<script>alert(1)</script>",
    "<svg onload=alert(1)>",
    "javascript:alert(1)",
]


async def test_sql_payload_is_stored_verbatim(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_task(
        client, auth_headers, title=SQL_PAYLOAD, description=SQL_PAYLOAD
    )

    listed = (await client.get(TASKS, headers=auth_headers)).json()

    assert created["title"] == SQL_PAYLOAD
    assert listed == [created]


async def test_sql_payload_does_not_alter_tables(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await create_task(client, auth_headers, title=SQL_PAYLOAD)

    # The tasks table still exists and accepts writes.
    await create_task(client, auth_headers, title="After payload")
    listed = (await client.get(TASKS, headers=auth_headers)).json()

    assert len(listed) == 2


async def test_sql_payload_in_login_is_rejected(client: httpx.AsyncClient) -> None:
    response = await login(client, email="' OR 1=1 --", password=SQL_PAYLOAD)
    assert response.status_code == 401


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
async def test_xss_payload_is_returned_as_json_text(
    client: httpx.AsyncClient, auth_headers: dict[str, str], payload: str
) -> None:
    created = await create_task(
        client, auth_headers, title=payload, description=payload
    )

    response = await client.get(TASKS, headers=auth_headers)

    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    task = response.json()[0]
    assert task["title"] == payload
    assert task["description"] == payload
    assert created["title"] == payload
