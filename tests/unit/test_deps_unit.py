"""Pure unit tests for FastAPI dependencies in app/api/deps.py."""

from datetime import datetime, timedelta, timezone
import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import HTTPException

from app.api.deps import (
    get_auth_service,
    get_current_user,
    get_email_validation_limiter,
    get_login_limiter,
    get_register_limiter,
    get_task_service,
)
from app.core.config import Settings
from app.core.security import create_access_token
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.task_service import TaskService


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        SECRET_KEY=secrets.token_urlsafe(48),
        BCRYPT_ROUNDS=4,
    )


async def test_get_current_user_accepts_valid_uuid_token() -> None:
    settings = _make_settings()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="ana@example.com",
        hashed_password="x",
        token_version=2,
    )
    users_repo = MagicMock(spec=UserRepository)
    users_repo.get_by_id = AsyncMock(return_value=user)
    token = create_access_token(str(user_id), version=2, settings=settings)

    resolved = await get_current_user(token=token, users=users_repo, settings=settings)

    assert resolved is user
    users_repo.get_by_id.assert_awaited_once_with(user_id)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"sub": "not-a-uuid", "ver": 0, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            id="non-uuid-sub",
        ),
        pytest.param(
            {"sub": 12345, "ver": 0, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            id="non-string-sub",
        ),
        pytest.param(
            {"ver": 0, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            id="missing-sub",
        ),
        pytest.param(
            {"sub": str(uuid.uuid4()), "ver": 0, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            id="expired-token",
        ),
    ],
)
async def test_get_current_user_rejects_invalid_jwt_without_db_lookup(
    payload: dict[str, object],
) -> None:
    settings = _make_settings()
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    users_repo = MagicMock(spec=UserRepository)
    users_repo.get_by_id = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, users=users_repo, settings=settings)

    assert exc.value.status_code == 401
    users_repo.get_by_id.assert_not_awaited()


async def test_get_current_user_rejects_wrong_signature() -> None:
    settings_a = _make_settings()
    settings_b = _make_settings()
    token = create_access_token(str(uuid.uuid4()), version=0, settings=settings_a)
    users_repo = MagicMock(spec=UserRepository)
    users_repo.get_by_id = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, users=users_repo, settings=settings_b)

    assert exc.value.status_code == 401
    users_repo.get_by_id.assert_not_awaited()


async def test_get_current_user_rejects_missing_user() -> None:
    settings = _make_settings()
    user_id = uuid.uuid4()
    token = create_access_token(str(user_id), version=0, settings=settings)
    users_repo = MagicMock(spec=UserRepository)
    users_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, users=users_repo, settings=settings)

    assert exc.value.status_code == 401
    users_repo.get_by_id.assert_awaited_once_with(user_id)


async def test_get_current_user_rejects_revoked_token_version() -> None:
    settings = _make_settings()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="ana@example.com",
        hashed_password="x",
        token_version=3,
    )
    token = create_access_token(str(user_id), version=2, settings=settings)
    users_repo = MagicMock(spec=UserRepository)
    users_repo.get_by_id = AsyncMock(return_value=user)

    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, users=users_repo, settings=settings)

    assert exc.value.status_code == 401
    users_repo.get_by_id.assert_awaited_once_with(user_id)


def test_dependency_factories_wire_services_and_limiters() -> None:
    settings = _make_settings()
    task_repo = MagicMock(spec=TaskRepository)
    user_repo = MagicMock(spec=UserRepository)

    assert isinstance(get_task_service(tasks=task_repo), TaskService)
    assert isinstance(get_auth_service(users=user_repo, settings=settings), AuthService)

    fake_request = MagicMock()
    fake_request.app.state.login_limiter = object()
    fake_request.app.state.register_limiter = object()
    fake_request.app.state.email_validation_limiter = object()

    assert get_login_limiter(fake_request) is fake_request.app.state.login_limiter
    assert get_register_limiter(fake_request) is fake_request.app.state.register_limiter
    assert (
        get_email_validation_limiter(fake_request)
        is fake_request.app.state.email_validation_limiter
    )
