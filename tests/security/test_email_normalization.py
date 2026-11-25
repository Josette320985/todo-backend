"""SEG-H09: registration and login use the same email normalization."""

import httpx

from app.core.emails import normalize_email
from conftest import TEST_PASSWORD, login
from helpers import register


def test_normalize_email_handles_unicode_and_idn() -> None:
    assert normalize_email(" USER@Example.COM ") == "user@example.com"
    assert normalize_email("user@bu\u0308cher.de") == "user@b\u00fccher.de"
    assert normalize_email("user@xn--bcher-kva.de") == "user@b\u00fccher.de"


async def test_unicode_email_can_log_in(client: httpx.AsyncClient) -> None:
    email = "user@bu\u0308cher.de"

    registered = await register(client, email, TEST_PASSWORD)
    assert registered.status_code == 201
    assert registered.json()["email"] == "user@b\u00fccher.de"

    response = await login(client, email=email)
    assert response.status_code == 200
    assert response.cookies.get("access_token")


async def test_idn_punycode_login_matches_unicode_registration(
    client: httpx.AsyncClient,
) -> None:
    registered = await register(client, "user@b\u00fccher.de", TEST_PASSWORD)
    assert registered.status_code == 201

    response = await login(client, email="user@xn--bcher-kva.de")
    assert response.status_code == 200


async def test_invalid_email_login_is_401(client: httpx.AsyncClient) -> None:
    response = await login(client, email="not-an-email")

    assert response.status_code == 401
