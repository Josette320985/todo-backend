"""
ARQ-01: create_app() builds independent apps from injected settings.

Acceptance criterion: two apps with different SECRET_KEY live in the same
process. Each one has its own database and only accepts its own tokens.
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

CREDENTIALS = {"email": "user@example.com", "password": "password123"}


def make_settings(db_path: Path, **overrides: object) -> Settings:
    """Settings built from explicit values, ignoring any local .env file."""
    values: dict[str, object] = {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "ENVIRONMENT": "test",
        "BCRYPT_ROUNDS": 4,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app lifespan (creates tables) and yield an in-process client."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


async def token_for(client: httpx.AsyncClient) -> str:
    """Register the default user and return a fresh access token."""
    await client.post("/api/v1/auth/register", json=CREDENTIALS)
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_apps_keep_their_own_settings(tmp_path: Path) -> None:
    settings_a = make_settings(tmp_path / "a.db")
    settings_b = make_settings(tmp_path / "b.db")

    app_a, app_b = create_app(settings_a), create_app(settings_b)

    assert app_a.state.settings is settings_a
    assert app_b.state.settings is settings_b
    assert app_a.state.engine is not app_b.state.engine


async def test_two_apps_with_different_secret_keys(tmp_path: Path) -> None:
    app_a = create_app(make_settings(tmp_path / "a.db"))
    app_b = create_app(make_settings(tmp_path / "b.db"))

    async with running(app_a) as client_a, running(app_b) as client_b:
        token_a = await token_for(client_a)
        # Same user (id 1, token_version 0) in B, so only the key differs.
        token_b = await token_for(client_b)

        assert (await client_a.get("/api/v1/tasks/", headers=bearer(token_a))).status_code == 200
        assert (await client_b.get("/api/v1/tasks/", headers=bearer(token_b))).status_code == 200
        assert (await client_b.get("/api/v1/tasks/", headers=bearer(token_a))).status_code == 401
        assert (await client_a.get("/api/v1/tasks/", headers=bearer(token_b))).status_code == 401


async def test_apps_use_separate_databases(tmp_path: Path) -> None:
    app_a = create_app(make_settings(tmp_path / "a.db"))
    app_b = create_app(make_settings(tmp_path / "b.db"))

    async with running(app_a) as client_a, running(app_b) as client_b:
        headers_a = bearer(await token_for(client_a))
        headers_b = bearer(await token_for(client_b))
        await client_a.post("/api/v1/tasks/", json={"title": "Only in A"}, headers=headers_a)

        tasks_a = (await client_a.get("/api/v1/tasks/", headers=headers_a)).json()
        tasks_b = (await client_b.get("/api/v1/tasks/", headers=headers_b)).json()

    assert [task["title"] for task in tasks_a] == ["Only in A"]
    assert tasks_b == []


async def test_docs_follow_injected_environment(tmp_path: Path) -> None:
    dev = create_app(make_settings(tmp_path / "dev.db", ENVIRONMENT="development"))
    prod = create_app(make_settings(tmp_path / "prod.db", ENVIRONMENT="production"))

    assert dev.openapi_url == "/api/openapi.json"
    assert prod.openapi_url is None
