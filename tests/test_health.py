"""
ERR-05: liveness (/api/health) and readiness (/api/health/ready).

The readiness criterion: with the database file inaccessible at startup,
/ready answers 503 (and compose does not mark the backend healthy, checked
in the E2E/compose healthcheck), while /api/health keeps answering 200.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import app.main as main
from app.core.config import Settings
from app.main import create_app
from conftest import TEST_EMAIL, TEST_PASSWORD
from helpers import register


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def unreachable_db_app(settings: Settings, tmp_path: Path) -> tuple[FastAPI, Path]:
    """App whose SQLite file lives in a directory that does not exist yet."""
    missing_dir: Path = tmp_path / "missing"
    url = f"sqlite+aiosqlite:///{(missing_dir / 'todo.db').as_posix()}"
    return create_app(settings.model_copy(update={"DATABASE_URL": url})), missing_dir


async def test_liveness_is_unchanged(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_is_200_with_a_working_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unreachable_database_at_startup_gives_503(
    settings: Settings, tmp_path: Path
) -> None:
    app, _ = unreachable_db_app(settings, tmp_path)

    # The lifespan does not crash: the process stays up to report the problem.
    async with running(app) as client:
        ready = await client.get("/api/health/ready")
        live = await client.get("/api/health")

    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
    assert live.status_code == 200


async def test_503_has_security_headers_and_no_error_details(
    settings: Settings, tmp_path: Path
) -> None:
    app, _ = unreachable_db_app(settings, tmp_path)
    async with running(app) as client:
        response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "sqlite" not in response.text.lower()
    assert "missing" not in response.text


async def test_ready_recovers_when_the_database_comes_back(
    settings: Settings, tmp_path: Path
) -> None:
    app, missing_dir = unreachable_db_app(settings, tmp_path)
    async with running(app) as client:
        assert (await client.get("/api/health/ready")).status_code == 503

        missing_dir.mkdir()

        # /ready runs the pending migrations, so the API works without a restart.
        assert (await client.get("/api/health/ready")).status_code == 200
        assert (await register(client, TEST_EMAIL, TEST_PASSWORD)).status_code == 201


async def test_ready_times_out_with_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stuck(app: FastAPI) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(main, "READINESS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "check_database", stuck)

    response = await client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
