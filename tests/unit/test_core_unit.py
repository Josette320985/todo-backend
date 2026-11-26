"""Pure unit tests for health/readiness checks and security primitives with mocks."""

import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from pytest_mock import MockerFixture
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.main import check_database, health, ready


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        SECRET_KEY=secrets.token_urlsafe(48),
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        BCRYPT_ROUNDS=4,
    )


async def test_health_returns_ok_without_db() -> None:
    assert await health() == {"status": "ok"}


async def test_check_database_retries_migration_once_when_not_migrated(
    mocker: MockerFixture,
) -> None:
    import asyncio

    migrate_mock = mocker.patch("app.main.migrate", new=AsyncMock())
    conn = AsyncMock()
    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)

    fake_app = MagicMock()
    fake_app.state.migrated = False
    fake_app.state.migrate_lock = asyncio.Lock()
    fake_app.state.engine.connect.return_value = conn_cm

    await check_database(fake_app)

    migrate_mock.assert_awaited_once_with(fake_app.state.engine)
    assert fake_app.state.migrated is True
    conn.execute.assert_awaited_once()


async def test_ready_returns_200_when_database_is_reachable(
    mocker: MockerFixture,
) -> None:
    check_mock = mocker.patch("app.main.check_database", new=AsyncMock())
    fake_request = MagicMock()

    response = await ready(fake_request)

    assert response.status_code == 200
    assert response.body == b'{"status":"ok"}'
    check_mock.assert_awaited_once_with(fake_request.app)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param(
            OperationalError("SELECT 1", {}, Exception("disk error")),
            id="operational-error",
        ),
    ],
)
async def test_ready_returns_503_without_leaking_error_details(
    mocker: MockerFixture, error: Exception
) -> None:
    mocker.patch("app.main.check_database", new=AsyncMock(side_effect=error))
    fake_request = MagicMock()

    response = await ready(fake_request)

    assert response.status_code == 503
    assert response.body == b'{"status":"unavailable"}'


def test_hash_and_verify_password_boundary_and_malformed_hash() -> None:
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("a" * 73, rounds=4)

    hashed = hash_password("Secret123", rounds=4)
    assert verify_password("Secret123", hashed) is True
    assert verify_password("Wrong123", hashed) is False
    assert verify_password("a" * 73, hashed) is False
    assert verify_password("Secret123", "not-a-valid-bcrypt-hash") is False


def test_create_access_token_embeds_uuid_subject_and_version() -> None:
    settings = _make_settings()
    subject = str(uuid.uuid4())

    token = create_access_token(subject, version=7, settings=settings)
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

    assert decoded["sub"] == subject
    assert decoded["ver"] == 7
    assert "iat" in decoded and "exp" in decoded
