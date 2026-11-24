"""Pure unit tests for AuthService using unittest.mock and pytest-mock.

No SQLite database, FastAPI app, or HTTP client is created: the UserRepository
and password-hashing helpers are mocked so every business rule is tested in
complete isolation.
"""

import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import EmailAlreadyRegistered, InvalidCredentials
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        SECRET_KEY=secrets.token_urlsafe(48),
        BCRYPT_ROUNDS=4,
    )


def _mock_user_repo() -> MagicMock:
    repo = MagicMock(spec=UserRepository)
    repo.get_by_email = AsyncMock(return_value=None)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda user: user)
    return repo


async def test_register_normalizes_email_hashes_password_and_persists() -> None:
    repo = _mock_user_repo()
    service = AuthService(repo, _make_settings())

    user = await service.register(
        UserCreate(email="Ana@Example.com", password="password123")
    )

    repo.get_by_email.assert_awaited_once_with("ana@example.com")
    repo.add.assert_awaited_once()
    assert user.email == "ana@example.com"
    assert user.hashed_password != "password123"
    assert user.hashed_password.startswith("$2")


async def test_register_duplicate_email_raises_without_hashing_or_saving(
    mocker: MockerFixture,
) -> None:
    existing = User(
        id=uuid.uuid4(),
        email="ana@example.com",
        hashed_password="$2b$04$existinghash",
    )
    repo = _mock_user_repo()
    repo.get_by_email.return_value = existing
    hash_spy = mocker.spy(
        __import__("app.services.auth_service", fromlist=["hash_password"]),
        "hash_password",
    )
    service = AuthService(repo, _make_settings())

    with pytest.raises(EmailAlreadyRegistered) as exc:
        await service.register(
            UserCreate(email="ANA@example.com", password="password123")
        )

    assert exc.value.status_code == 400
    repo.get_by_email.assert_awaited_once_with("ana@example.com")
    repo.add.assert_not_awaited()
    hash_spy.assert_not_called()


async def test_register_race_condition_translates_integrity_error() -> None:
    repo = _mock_user_repo()
    repo.get_by_email.return_value = None
    repo.add.side_effect = IntegrityError("INSERT", {}, Exception("UNIQUE"))
    service = AuthService(repo, _make_settings())

    with pytest.raises(EmailAlreadyRegistered) as exc:
        await service.register(
            UserCreate(email="ana@example.com", password="password123")
        )

    assert exc.value.status_code == 400
    repo.add.assert_awaited_once()


async def test_authenticate_valid_credentials(mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    stored_user = User(
        id=user_id,
        email="ana@example.com",
        hashed_password=hash_password("password123", rounds=4),
    )
    repo = _mock_user_repo()
    repo.get_by_email.return_value = stored_user
    log_mock = mocker.patch("app.services.auth_service._log_failed_login")
    service = AuthService(repo, _make_settings())

    user = await service.authenticate("ANA@example.com", "password123", "127.0.0.1")

    assert user is stored_user
    assert user.id == user_id
    repo.get_by_email.assert_awaited_once_with("ana@example.com")
    log_mock.assert_not_called()


async def test_authenticate_wrong_password_logs_and_raises(
    mocker: MockerFixture,
) -> None:
    stored_user = User(
        id=uuid.uuid4(),
        email="ana@example.com",
        hashed_password="$2b$04$storedhash",
    )
    repo = _mock_user_repo()
    repo.get_by_email.return_value = stored_user
    verify_mock = mocker.patch(
        "app.services.auth_service.verify_password", return_value=False
    )
    log_mock = mocker.patch("app.services.auth_service._log_failed_login")
    service = AuthService(repo, _make_settings())

    with pytest.raises(InvalidCredentials) as exc:
        await service.authenticate("ana@example.com", "wrong1234", "10.0.0.5")

    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}
    verify_mock.assert_called_once_with("wrong1234", "$2b$04$storedhash")
    log_mock.assert_called_once_with("ana@example.com", "10.0.0.5")


async def test_authenticate_unknown_email_runs_dummy_hash_defense(
    mocker: MockerFixture,
) -> None:
    repo = _mock_user_repo()
    repo.get_by_email.return_value = None
    dummy_mock = mocker.patch(
        "app.services.auth_service.dummy_password_hash",
        return_value="$2b$04$dummyhash",
    )
    verify_mock = mocker.patch(
        "app.services.auth_service.verify_password", return_value=False
    )
    log_mock = mocker.patch("app.services.auth_service._log_failed_login")
    service = AuthService(repo, _make_settings())

    with pytest.raises(InvalidCredentials):
        await service.authenticate("nadie@example.com", "password123", "127.0.0.1")

    repo.get_by_email.assert_awaited_once_with("nadie@example.com")
    dummy_mock.assert_called_once_with(4)
    verify_mock.assert_called_once_with("password123", "$2b$04$dummyhash")
    log_mock.assert_called_once_with("nadie@example.com", "127.0.0.1")


async def test_authenticate_invalid_email_skips_repository_lookup(
    mocker: MockerFixture,
) -> None:
    repo = _mock_user_repo()
    mocker.patch(
        "app.services.auth_service.dummy_password_hash",
        return_value="$2b$04$dummyhash",
    )
    verify_mock = mocker.patch(
        "app.services.auth_service.verify_password", return_value=False
    )
    log_mock = mocker.patch("app.services.auth_service._log_failed_login")
    service = AuthService(repo, _make_settings())

    with pytest.raises(InvalidCredentials):
        await service.authenticate("not-an-email", "password123", "127.0.0.1")

    repo.get_by_email.assert_not_awaited()
    verify_mock.assert_called_once_with("password123", "$2b$04$dummyhash")
    log_mock.assert_called_once_with("not-an-email", "127.0.0.1")
