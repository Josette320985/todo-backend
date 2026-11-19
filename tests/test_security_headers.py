"""Tests for the pure-ASGI security headers middleware (PERF-02)."""

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_current_user
from app.core.logging import REQUEST_ID_HEADER

# SEC-07: the exact set of headers the middleware must keep.
EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cache-control": "no-store",
}


def assert_security_headers(response: httpx.Response) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, (name, dict(response.headers))


async def test_headers_on_200(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert_security_headers(response)


async def test_headers_on_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/")

    assert response.status_code == 401
    assert_security_headers(response)


async def test_headers_on_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/no-existe")

    assert response.status_code == 404
    assert_security_headers(response)


async def test_headers_on_422(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json={"email": "no-es-email"})

    assert response.status_code == 422
    assert_security_headers(response)


async def test_headers_on_500(app: FastAPI, client: httpx.AsyncClient) -> None:
    """A 500 from the error path also carries the headers (PERF-02)."""

    async def explode() -> None:
        raise RuntimeError("fallo provocado")

    app.dependency_overrides[get_current_user] = explode

    response = await client.get("/api/v1/tasks/")

    assert response.status_code == 500
    assert_security_headers(response)
    # The other middleware still ran: the id is there too (ERR-04).
    assert response.headers.get(REQUEST_ID_HEADER)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def test_headers_on_cors_preflight_and_methods(
    client: httpx.AsyncClient, method: str
) -> None:
    response = await client.request(
        method,
        "/api/health",
        headers={"Origin": "http://localhost:3000"},
    )

    assert_security_headers(response)


def test_no_base_http_middleware_in_the_stack(app: FastAPI) -> None:
    """Guard the regression: BaseHTTPMiddleware must not come back."""
    from starlette.middleware.base import BaseHTTPMiddleware

    from app.main import SecurityHeadersMiddleware

    classes = [middleware.cls for middleware in app.user_middleware]
    assert SecurityHeadersMiddleware in classes
    assert not any(issubclass(cls, BaseHTTPMiddleware) for cls in classes)
    # Outermost first: the headers wrap the rest, including the 500 path.
    assert classes[0] is SecurityHeadersMiddleware
