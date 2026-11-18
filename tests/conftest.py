"""
Shared test fixtures.

The environment is configured BEFORE importing the app, because
`settings` and the database engine are created at import time.
Each test gets a fresh SQLite file database and a random SECRET_KEY,
so the real `.env` and `data/todo.db` are never touched.
"""

import os
import secrets
import tempfile
from collections.abc import AsyncIterator

_TMP_DIR: str = tempfile.mkdtemp(prefix="todo-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR}/test.db"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["ENVIRONMENT"] = "test"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.api.v1 import auth  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402

TEST_EMAIL: str = "user@example.com"
TEST_PASSWORD: str = "password123"


@pytest.fixture(autouse=True)
async def _fresh_state() -> AsyncIterator[None]:
    """Create empty tables and reset rate limits for every test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    auth._rate_limit_buckets.clear()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    # Each test runs in its own event loop: drop pooled connections.
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client that calls the app in-process (no server needed)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c


async def login(
    client: httpx.AsyncClient,
    email: str = TEST_EMAIL,
    password: str = TEST_PASSWORD,
) -> httpx.Response:
    """POST the login form and return the raw response."""
    return await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )


@pytest.fixture
async def auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Register the default user and return its Authorization header."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    token: str = (await login(client)).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
