"""
TEST-01: the test base itself works as documented in conftest.py.
"""

import secrets

import bcrypt
import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import dummy_password_hash, hash_password
from conftest import TEST_BCRYPT_ROUNDS, QueryLog, TestUser


def _settings(**values: object) -> Settings:
    return Settings(  # type: ignore[arg-type]
        _env_file=None, SECRET_KEY=secrets.token_urlsafe(48), **values
    )


async def test_example_request(client: httpx.AsyncClient) -> None:
    # Acceptance criterion of TEST-01: an example test runs in under 1 s
    # (see `pytest --durations`).
    response = await client.get("/api/health")
    assert response.status_code == 200


def test_app_uses_test_settings(app: FastAPI, settings: Settings) -> None:
    assert app.state.settings is settings
    assert settings.ENVIRONMENT == "test"
    assert settings.BCRYPT_ROUNDS == TEST_BCRYPT_ROUNDS
    assert settings.DATABASE_URL.endswith("/test.db")


async def test_users_are_distinct(user: TestUser, other_user: TestUser) -> None:
    assert user.id != other_user.id
    assert user.headers != other_user.headers


async def test_count_queries_records_statements(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    count_queries: QueryLog,
) -> None:
    count_queries.clear()

    await client.get("/api/v1/tasks/", headers=auth_headers)

    assert count_queries.count >= 1
    assert any("FROM tasks" in statement for statement in count_queries)


def test_bcrypt_rounds_default_is_12() -> None:
    assert _settings().BCRYPT_ROUNDS == 12


@pytest.mark.parametrize("rounds", [3, 32])
def test_bcrypt_rounds_out_of_range_is_rejected(rounds: int) -> None:
    with pytest.raises(ValidationError):
        _settings(BCRYPT_ROUNDS=rounds)


@pytest.mark.parametrize("rounds", [4, 5])
def test_hashes_use_configured_rounds(rounds: int) -> None:
    for hashed in (hash_password("password123", rounds), dummy_password_hash(rounds)):
        # bcrypt hashes look like $2b$<rounds>$...
        assert hashed.split("$")[2] == f"{rounds:02d}"
    assert bcrypt.checkpw(b"password123", hash_password("password123", rounds).encode())
