"""
TEST-03: authentication hardening that already works (report sections 3
and 4: "Login", SEC-04 and SEC-07).
"""

import httpx
import pytest

from conftest import TEST_EMAIL, TEST_PASSWORD, login
from helpers import register


async def test_unknown_email_and_wrong_password_look_the_same(
    client: httpx.AsyncClient,
) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    unknown = await login(client, email="nobody@example.com")
    wrong = await login(client, password="wrong-password1")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown.headers.get("www-authenticate") == wrong.headers.get(
        "www-authenticate"
    )


async def test_password_over_72_bytes_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    # 37 x "ñ" = 74 UTF-8 bytes, under 72 characters (SEC-04).
    response = await register(client, TEST_EMAIL, "ñ" * 36 + "a1")
    assert response.status_code == 422


async def test_login_with_password_over_72_bytes_is_401(
    client: httpx.AsyncClient,
) -> None:
    await register(client, TEST_EMAIL, TEST_PASSWORD)

    response = await login(client, password="ñ" * 40)

    assert response.status_code == 401


async def test_register_response_never_exposes_password(
    client: httpx.AsyncClient,
) -> None:
    response = await register(client, TEST_EMAIL, TEST_PASSWORD)

    text = response.text.lower()
    assert "password" not in text
    assert TEST_PASSWORD not in response.text


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("cache-control", "no-store"),
    ],
)
@pytest.mark.parametrize(
    "path", ["/api/health", "/api/v1/tasks/"], ids=["200", "401"]
)
async def test_security_headers_on_api_responses(
    client: httpx.AsyncClient, path: str, header: str, value: str
) -> None:
    response = await client.get(path)
    assert response.headers[header] == value
