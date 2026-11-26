"""Tests for Prometheus HTTP metrics instrumentation (/metrics)."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.logging import REQUEST_ID_HEADER
from app.core.metrics import METRICS_ENDPOINT
from app.main import create_app


def _make_settings(db_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "ENVIRONMENT": "test",
        "BCRYPT_ROUNDS": 4,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@asynccontextmanager
async def _running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


async def test_metrics_endpoint_returns_prometheus_format(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(METRICS_ENDPOINT)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers.get(REQUEST_ID_HEADER)
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_metrics_record_requests_latency_and_exact_status_codes(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/api/health")).status_code == 200
    assert (await client.get("/api/v1/tasks/")).status_code == 401

    metrics_response = await client.get(METRICS_ENDPOINT)
    body = metrics_response.text

    assert metrics_response.status_code == 200
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert 'handler="/api/health"' in body
    assert 'status="200"' in body
    assert 'handler="/api/v1/tasks/"' in body
    assert 'status="401"' in body


async def test_metrics_endpoint_is_excluded_from_request_counters(
    client: httpx.AsyncClient,
) -> None:
    await client.get(METRICS_ENDPOINT)
    await client.get(METRICS_ENDPOINT)
    body = (await client.get(METRICS_ENDPOINT)).text

    assert f'handler="{METRICS_ENDPOINT}"' not in body


async def test_metrics_endpoint_is_hidden_from_openapi_schema(
    tmp_path: Path,
) -> None:
    dev_app = create_app(
        _make_settings(tmp_path / "dev.db", ENVIRONMENT="development")
    )
    async with _running(dev_app) as client:
        schema = (await client.get("/api/openapi.json")).json()

    assert METRICS_ENDPOINT not in schema["paths"]


async def test_metrics_registries_are_isolated_between_apps(
    tmp_path: Path,
) -> None:
    app_a = create_app(_make_settings(tmp_path / "a.db"))
    app_b = create_app(_make_settings(tmp_path / "b.db"))

    assert app_a.state.metrics_registry is not app_b.state.metrics_registry

    async with _running(app_a) as client_a, _running(app_b) as client_b:
        assert (await client_a.get("/api/health")).status_code == 200

        metrics_a = (await client_a.get(METRICS_ENDPOINT)).text
        metrics_b = (await client_b.get(METRICS_ENDPOINT)).text

    assert 'handler="/api/health"' in metrics_a
    assert 'handler="/api/health"' not in metrics_b


async def test_metrics_can_be_disabled_via_settings(tmp_path: Path) -> None:
    app = create_app(_make_settings(tmp_path / "disabled.db", METRICS_ENABLED=False))
    async with _running(app) as client:
        response = await client.get(METRICS_ENDPOINT)

    assert response.status_code == 404
