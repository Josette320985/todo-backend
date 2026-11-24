"""Pure unit tests for TaskRepository and UserRepository mocking AsyncSession."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.user import User
from app.repositories.task_repository import TaskRepository, build_task_order
from app.repositories.user_repository import UserRepository
from app.utils.task_sorting import SortOrder, TaskSortField


def _mock_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


async def test_user_repository_queries_mocked_session() -> None:
    session = _mock_session()
    user_id = uuid.uuid4()
    user = User(id=user_id, email="ana@example.com", hashed_password="h")
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = user
    session.execute.return_value = result_mock
    repo = UserRepository(session)

    assert await repo.get_by_id(user_id) is user
    assert await repo.get_by_email("ana@example.com") is user
    assert session.execute.await_count == 2


async def test_user_repository_add_commits_and_refreshes() -> None:
    session = _mock_session()
    user = User(id=uuid.uuid4(), email="ana@example.com", hashed_password="h")
    repo = UserRepository(session)

    saved = await repo.add(user)

    assert saved is user
    session.add.assert_called_once_with(user)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)
    session.rollback.assert_not_awaited()


async def test_user_repository_add_rolls_back_on_integrity_error() -> None:
    session = _mock_session()
    session.commit.side_effect = IntegrityError("INSERT", {}, Exception("UNIQUE"))
    user = User(id=uuid.uuid4(), email="ana@example.com", hashed_password="h")
    repo = UserRepository(session)

    with pytest.raises(IntegrityError):
        await repo.add(user)

    session.rollback.assert_awaited_once()
    session.refresh.assert_not_awaited()


async def test_task_repository_add_skips_refresh_opt03() -> None:
    session = _mock_session()
    task = Task(id=uuid.uuid4(), owner_id=uuid.uuid4(), title="Sin refresh")
    repo = TaskRepository(session)

    saved = await repo.add(task)

    assert saved is task
    session.add.assert_called_once_with(task)
    session.commit.assert_awaited_once()
    session.refresh.assert_not_awaited()


@pytest.mark.parametrize(
    ("rowcount", "expected"),
    [pytest.param(1, True, id="deleted"), pytest.param(0, False, id="not-found")],
)
async def test_task_repository_delete_owned_uses_single_query_opt04(
    rowcount: int, expected: bool
) -> None:
    session = _mock_session()
    cursor = MagicMock(rowcount=rowcount)
    session.execute.return_value = cursor
    repo = TaskRepository(session)

    deleted = await repo.delete_owned(uuid.uuid4(), uuid.uuid4())

    assert deleted is expected
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_task_repository_list_count_and_get_owned() -> None:
    session = _mock_session()
    owner_id = uuid.uuid4()
    task = Task(id=uuid.uuid4(), owner_id=owner_id, title="Mocked")
    repo = TaskRepository(session)

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [task]
    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = task
    session.execute.side_effect = [list_result, count_result, get_result]

    assert await repo.list_by_owner(owner_id, limit=10, offset=5, completed=False) == [
        task
    ]
    assert await repo.count_by_owner(owner_id) == 3
    assert await repo.get_owned(task.id, owner_id) is task
    assert session.execute.await_count == 3


def test_build_task_order_deduplicates_fields_and_adds_id_tiebreaker() -> None:
    default_clauses = build_task_order()
    assert len(default_clauses) == 4  # completed, end_date IS NULL, end_date, id

    custom_clauses = build_task_order(
        [TaskSortField.TITLE, TaskSortField.TITLE], SortOrder.DESC
    )
    assert len(custom_clauses) == 2  # lower(title) DESC + id tie-breaker

    explicit_id_clauses = build_task_order([TaskSortField.ID], SortOrder.DESC)
    assert len(explicit_id_clauses) == 1  # id DESC without duplicate tie-breaker
