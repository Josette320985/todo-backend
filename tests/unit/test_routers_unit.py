"""Pure unit tests for API v1 routers (auth.py and tasks.py) with mocks."""

import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from app.api.v1 import auth as auth_router
from app.api.v1 import tasks as tasks_router
from app.core.config import Settings
from app.core.errors import InvalidCredentials, RateLimited
from app.core.rate_limit import LoginRateLimiter, RateLimiter
from app.models.task import Task
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.user import EmailValidationRequest, UserCreate
from app.services.auth_service import AuthService
from app.services.task_service import TaskService
from app.utils.task_sorting import SortOrder, TaskSortField


def _fake_request(host: str | None = "198.51.100.10") -> MagicMock:
    req = MagicMock()
    if host is None:
        req.client = None
    else:
        req.client = MagicMock(host=host)
    return req


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        SECRET_KEY=secrets.token_urlsafe(48),
        BCRYPT_ROUNDS=4,
    )


async def test_validate_email_endpoint_checks_rate_limit_and_normalizes() -> None:
    limiter = MagicMock(spec=RateLimiter)
    result = await auth_router.validate_registration_email(
        request=_fake_request("10.0.0.1"),
        payload=EmailValidationRequest(email="  Ana@Example.COM "),
        limiter=limiter,
    )

    limiter.check.assert_called_once_with("10.0.0.1")
    assert result.valid is True
    assert result.normalized == "ana@example.com"


async def test_register_endpoint_delegates_after_rate_limit() -> None:
    limiter = MagicMock(spec=RateLimiter)
    expected_user = User(id=uuid.uuid4(), email="ana@example.com", hashed_password="h")
    service = MagicMock(spec=AuthService)
    service.register = AsyncMock(return_value=expected_user)
    payload = UserCreate(email="ana@example.com", password="password123")

    result = await auth_router.register(
        request=_fake_request("10.0.0.2"),
        payload=payload,
        service=service,
        limiter=limiter,
    )

    limiter.check.assert_called_once_with("10.0.0.2")
    service.register.assert_awaited_once_with(payload)
    assert result is expected_user


async def test_register_endpoint_blocks_service_when_rate_limited() -> None:
    limiter = MagicMock(spec=RateLimiter)
    limiter.check.side_effect = RateLimited(retry_after=30)
    service = MagicMock(spec=AuthService)
    service.register = AsyncMock()
    payload = UserCreate(email="ana@example.com", password="password123")

    with pytest.raises(RateLimited):
        await auth_router.register(
            request=_fake_request(None),
            payload=payload,
            service=service,
            limiter=limiter,
        )

    limiter.check.assert_called_once_with("unknown")
    service.register.assert_not_awaited()


async def test_login_endpoint_issues_token_and_clears_attempt_on_success(
    mocker: MockerFixture,
) -> None:
    settings = _make_settings()
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="ana@example.com",
        hashed_password="h",
        token_version=4,
    )
    limiter = MagicMock(spec=LoginRateLimiter)
    service = MagicMock(spec=AuthService)
    service.authenticate = AsyncMock(return_value=user)
    token_mock = mocker.patch(
        "app.api.v1.auth.create_access_token", return_value="jwt-token-value"
    )
    form = MagicMock(username="ana@example.com", password="password123")

    response = await auth_router.login(
        request=_fake_request("10.0.0.3"),
        form=form,
        service=service,
        settings=settings,
        limiter=limiter,
    )

    limiter.check.assert_called_once_with("10.0.0.3", "ana@example.com")
    service.authenticate.assert_awaited_once_with(
        "ana@example.com", "password123", "10.0.0.3"
    )
    limiter.succeeded.assert_called_once_with("10.0.0.3", "ana@example.com")
    token_mock.assert_called_once_with(str(user_id), 4, settings)
    assert response == {"access_token": "jwt-token-value", "token_type": "bearer"}


async def test_login_endpoint_keeps_failed_attempt_counted_on_invalid_credentials() -> None:
    settings = _make_settings()
    limiter = MagicMock(spec=LoginRateLimiter)
    service = MagicMock(spec=AuthService)
    service.authenticate = AsyncMock(side_effect=InvalidCredentials())
    form = MagicMock(username="ana@example.com", password="wrong")

    with pytest.raises(InvalidCredentials):
        await auth_router.login(
            request=_fake_request("10.0.0.4"),
            form=form,
            service=service,
            settings=settings,
            limiter=limiter,
        )

    limiter.check.assert_called_once_with("10.0.0.4", "ana@example.com")
    limiter.succeeded.assert_not_called()


async def test_me_and_logout_endpoints() -> None:
    user = User(
        id=uuid.uuid4(),
        email="ana@example.com",
        hashed_password="h",
        token_version=1,
    )
    assert await auth_router.read_current_user(current_user=user) is user

    users_repo = MagicMock(spec=UserRepository)
    users_repo.add = AsyncMock(return_value=user)
    await auth_router.logout(user=user, users=users_repo)

    assert user.token_version == 2
    users_repo.add.assert_awaited_once_with(user)


async def test_tasks_router_delegates_every_operation_with_uuids() -> None:
    user = User(id=uuid.uuid4(), email="ana@example.com", hashed_password="h")
    task_id = uuid.uuid4()
    task = Task(id=task_id, owner_id=user.id, title="Mocked")
    service = MagicMock(spec=TaskService)
    service.list_tasks = AsyncMock(return_value=[task])
    service.create_task = AsyncMock(return_value=task)
    service.update_task = AsyncMock(return_value=task)
    service.delete_task = AsyncMock(return_value=None)

    listed = await tasks_router.list_tasks(
        limit=25,
        offset=10,
        completed=True,
        sort_by=[TaskSortField.END_DATE],
        order=SortOrder.DESC,
        service=service,
        current_user=user,
    )
    assert listed == [task]
    service.list_tasks.assert_awaited_once_with(
        user.id,
        limit=25,
        offset=10,
        completed=True,
        sort_by=[TaskSortField.END_DATE],
        order=SortOrder.DESC,
    )

    create_payload = TaskCreate(title="Nueva")
    assert (
        await tasks_router.create_task(
            payload=create_payload, service=service, current_user=user
        )
        is task
    )
    service.create_task.assert_awaited_once_with(user.id, create_payload)

    update_payload = TaskUpdate(completed=True)
    assert (
        await tasks_router.update_task(
            task_id=task_id,
            payload=update_payload,
            service=service,
            current_user=user,
        )
        is task
    )
    service.update_task.assert_awaited_once_with(task_id, user.id, update_payload)

    await tasks_router.delete_task(
        task_id=task_id, service=service, current_user=user
    )
    service.delete_task.assert_awaited_once_with(task_id, user.id)
