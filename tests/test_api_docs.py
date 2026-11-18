"""SEG-H07: API docs are only published in the development environment."""

import httpx
import pytest

from app.main import api_docs_urls

DOCS_PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


@pytest.mark.parametrize("env", ["development", "DEVELOPMENT", " Development "])
def test_docs_enabled_in_development(env: str) -> None:
    assert api_docs_urls(env) == DOCS_PATHS


@pytest.mark.parametrize(
    "env", ["production", "Production", "PRODUCTION", "staging", "test", "dev", ""]
)
def test_docs_disabled_outside_development(env: str) -> None:
    assert api_docs_urls(env) == (None, None, None)


@pytest.mark.parametrize("path", DOCS_PATHS)
async def test_docs_routes_return_404_outside_development(
    client: httpx.AsyncClient, path: str
) -> None:
    # conftest.py runs the app with ENVIRONMENT=test.
    response = await client.get(path)
    assert response.status_code == 404


async def test_health_still_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
