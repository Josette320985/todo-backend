import httpx
import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate


@pytest.mark.parametrize("email", [
    " User@Example.COM ", "user+tag@example.com", "josé@example.com",
    "user@bücher.de", "user@xn--bcher-kva.de", "用户@例子.公司",
    "", "invalid", "a..b@example.com", ".a@example.com", "a.@example.com",
    "a b@example.com", "a@localhost", "a@-example.com", "a@example..com",
    "a@example.test", "a@example.123", "a@xn--invalid-.com",
    "a" * 65 + "@example.com", "a@" + "b" * 64 + ".com",
    "a\u200b@example.com", "a@💩.com", "Name <user@example.com>",
])
async def test_validation_matches_registration_schema(client: httpx.AsyncClient, email: str) -> None:
    try:
        expected = UserCreate(email=email, password="Password1").email
    except ValidationError:
        expected = None
    response = await client.post("/api/v1/auth/validate-email", json={"email": email})
    assert response.status_code == 200
    assert response.json()["valid"] is (expected is not None)
    assert response.json()["normalized"] == expected


async def test_validation_does_not_disclose_account_existence(client: httpx.AsyncClient) -> None:
    payload = {"email": "private@example.com"}
    before = await client.post("/api/v1/auth/validate-email", json=payload)
    await client.post("/api/v1/auth/register", json={**payload, "password": "Password1"})
    after = await client.post("/api/v1/auth/validate-email", json=payload)
    assert before.json() == after.json()


async def test_validation_has_separate_rate_limit(client: httpx.AsyncClient) -> None:
    for _ in range(60):
        response = await client.post("/api/v1/auth/validate-email", json={"email": "bad"})
        assert response.status_code == 200
    assert (await client.post("/api/v1/auth/validate-email", json={"email": "bad"})).status_code == 429
    assert (await client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "Password1"})).status_code == 201
