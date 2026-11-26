"""
TEST-02: characterization of the auth endpoints.

Black-box tests that pin the current behaviour of /auth/register and
/auth/login before the refactor (ARQ-02, ARQ-04). They assert status
codes and response shapes, not error message texts, because ERR-02 will
change the error format on purpose.
"""

import uuid

import httpx
import pytest

from conftest import TEST_EMAIL, TEST_PASSWORD, login
from helpers import register


async def test_register_returns_201_with_public_fields(
    client: httpx.AsyncClient,
) -> None:
    response = await register(client, TEST_EMAIL, TEST_PASSWORD)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email"}
    assert body["email"] == TEST_EMAIL
    assert uuid.UUID(body["id"])


async def test_register_normalizes_email(client: httpx.AsyncClient) -> None:
    response = await register(client, "User@Example.COM", TEST_PASSWORD)

    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"


async def test_register_duplicate_email_is_400(client: httpx.AsyncClient) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    response = await register(client, TEST_EMAIL.upper(), TEST_PASSWORD)

    assert response.status_code == 400


async def test_register_invalid_email_is_422(client: httpx.AsyncClient) -> None:
    response = await register(client, "not-an-email", TEST_PASSWORD)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "password",
    ["short1", "onlyletters", "12345678", " " * 8],
    ids=["too-short", "no-digit", "no-letter", "only-spaces"],
)
async def test_register_weak_password_is_422(
    client: httpx.AsyncClient, password: str
) -> None:
    response = await register(client, TEST_EMAIL, password)
    assert response.status_code == 422


async def test_login_sets_httponly_cookie(client: httpx.AsyncClient) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    response = await login(client)

    assert response.status_code == 200
    assert "access_token" not in response.json()
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "access_token=" in cookie_header
    assert "httponly" in cookie_header


async def test_login_email_is_case_insensitive(client: httpx.AsyncClient) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    response = await login(client, email=" USER@example.com ")

    assert response.status_code == 200


async def test_login_wrong_password_is_401(client: httpx.AsyncClient) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    response = await login(client, password="wrong-password1")

    assert response.status_code == 401


async def test_login_missing_fields_is_422(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", data={})
    assert response.status_code == 422
