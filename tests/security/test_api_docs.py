"""
SEG-H07: the API docs (OpenAPI schema, Swagger UI and ReDoc) are only
served when ENVIRONMENT is "development". Any other value, including
"Production" or a typo, keeps them closed.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

DOC_PATHS: tuple[str, ...] = ("/api/openapi.json", "/api/docs", "/api/redoc")


def app_with(settings: Settings, environment: str) -> FastAPI:
    return create_app(settings.model_copy(update={"ENVIRONMENT": environment}))


async def get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path)


@pytest.mark.parametrize(
    "environment",
    ["production", "Production", "PRODUCTION", " production ", "prod", "staging", "test", ""],
)
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_are_404_outside_development(
    settings: Settings, environment: str, path: str
) -> None:
    response = await get(app_with(settings, environment), path)
    assert response.status_code == 404


@pytest.mark.parametrize("environment", ["development", "Development", " DEVELOPMENT "])
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_are_served_in_development(
    settings: Settings, environment: str, path: str
) -> None:
    response = await get(app_with(settings, environment), path)
    assert response.status_code == 200


async def test_api_still_works_without_docs(settings: Settings) -> None:
    response = await get(app_with(settings, "production"), "/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
