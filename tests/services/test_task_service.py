"""Pure unit tests for TaskService using unittest.mock and pytest-mock.

All repository interactions are mocked so TaskService business rules
(ownership delegation, pagination cap, per-user task limit, allowlisted partial
updates, and date validation) run deterministically without touching SQLite.
"""

from datetime import date
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import NotFoundError, TaskLimitReached, ValidationFailed
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_service import (
    MAX_PAGE_SIZE,
    MAX_TASKS_PER_USER,
    TaskService,
)
from app.utils.task_sorting import SortOrder, TaskSortField


def _mock_task_repo() -> MagicMock:
    repo = MagicMock(spec=TaskRepository)
    repo.list_by_owner = AsyncMock(return_value=[])
    repo.count_by_owner = AsyncMock(return_value=0)
    repo.get_owned = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda task: task)
    repo.delete_owned = AsyncMock(return_value=True)
    return repo


def _make_task(
    owner_id: uuid.UUID,
    *,
    title: str = "Original",
    description: str | None = "Detalle",
    completed: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Task:
    return Task(
        id=uuid.uuid4(),
        owner_id=owner_id,
        title=title,
        description=description,
        completed=completed,
        start_date=start_date,
        end_date=end_date,
    )


async def test_list_tasks_applies_default_page_size_and_forwards_filters() -> None:
    owner_id = uuid.uuid4()
    expected = [_make_task(owner_id, title="Una")]
    repo = _mock_task_repo()
    repo.list_by_owner.return_value = expected
    service = TaskService(repo)

    result = await service.list_tasks(
        owner_id,
        offset=5,
        completed=False,
        sort_by=[TaskSortField.TITLE],
        order=SortOrder.DESC,
    )

    assert result == expected
    repo.list_by_owner.assert_awaited_once_with(
        owner_id,
        limit=MAX_PAGE_SIZE,
        offset=5,
        completed=False,
        sort_by=[TaskSortField.TITLE],
        order=SortOrder.DESC,
    )


async def test_list_tasks_caps_limit_at_max_page_size() -> None:
    owner_id = uuid.uuid4()
    repo = _mock_task_repo()
    service = TaskService(repo)

    await service.list_tasks(owner_id, limit=MAX_PAGE_SIZE + 250)

    repo.list_by_owner.assert_awaited_once_with(
        owner_id,
        limit=MAX_PAGE_SIZE,
        offset=0,
        completed=None,
        sort_by=None,
        order=SortOrder.ASC,
    )


async def test_create_task_persists_with_owner_uuid() -> None:
    owner_id = uuid.uuid4()
    repo = _mock_task_repo()
    service = TaskService(repo)

    created = await service.create_task(owner_id, TaskCreate(title="  Comprar pan  "))

    assert created.owner_id == owner_id
    assert created.title == "Comprar pan"
    repo.count_by_owner.assert_awaited_once_with(owner_id)
    repo.add.assert_awaited_once_with(created)


async def test_create_task_enforces_per_user_cap() -> None:
    owner_id = uuid.uuid4()
    repo = _mock_task_repo()
    repo.count_by_owner.return_value = MAX_TASKS_PER_USER
    service = TaskService(repo)

    with pytest.raises(TaskLimitReached) as exc:
        await service.create_task(owner_id, TaskCreate(title="Bloqueada"))

    assert exc.value.status_code == 409
    repo.add.assert_not_awaited()


async def test_partial_update_keeps_untouched_fields() -> None:
    owner_id = uuid.uuid4()
    stored = _make_task(owner_id, title="Original", description="Detalle")
    repo = _mock_task_repo()
    repo.get_owned.return_value = stored
    service = TaskService(repo)

    updated = await service.update_task(
        stored.id, owner_id, TaskUpdate(completed=True)
    )

    assert updated is stored
    assert updated.completed is True
    assert updated.title == "Original"
    assert updated.description == "Detalle"
    repo.get_owned.assert_awaited_once_with(stored.id, owner_id)
    repo.add.assert_awaited_once_with(stored)


async def test_update_validates_dates_against_stored_values() -> None:
    owner_id = uuid.uuid4()
    stored = _make_task(owner_id, start_date=date(2026, 11, 10))
    repo = _mock_task_repo()
    repo.get_owned.return_value = stored
    service = TaskService(repo)

    with pytest.raises(ValidationFailed) as exc:
        await service.update_task(
            stored.id, owner_id, TaskUpdate(end_date=date(2026, 11, 1))
        )

    assert exc.value.status_code == 422
    assert exc.value.errors[0].field == "end_date"
    repo.add.assert_not_awaited()


async def test_update_accepts_valid_range() -> None:
    owner_id = uuid.uuid4()
    stored = _make_task(
        owner_id,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 10),
    )
    repo = _mock_task_repo()
    repo.get_owned.return_value = stored
    service = TaskService(repo)

    updated = await service.update_task(
        stored.id, owner_id, TaskUpdate(end_date=date(2026, 11, 5))
    )

    assert updated.end_date == date(2026, 11, 5)
    repo.add.assert_awaited_once_with(stored)


async def test_update_missing_or_foreign_task_raises_not_found() -> None:
    owner_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    repo = _mock_task_repo()
    repo.get_owned.return_value = None
    service = TaskService(repo)

    with pytest.raises(NotFoundError) as exc:
        await service.update_task(missing_id, owner_id, TaskUpdate(title="x"))

    assert exc.value.status_code == 404
    repo.get_owned.assert_awaited_once_with(missing_id, owner_id)
    repo.add.assert_not_awaited()


async def test_delete_owned_task_succeeds() -> None:
    owner_id = uuid.uuid4()
    task_id = uuid.uuid4()
    repo = _mock_task_repo()
    repo.delete_owned.return_value = True
    service = TaskService(repo)

    await service.delete_task(task_id, owner_id)

    repo.delete_owned.assert_awaited_once_with(task_id, owner_id)


async def test_delete_missing_or_foreign_task_raises_not_found() -> None:
    owner_id = uuid.uuid4()
    task_id = uuid.uuid4()
    repo = _mock_task_repo()
    repo.delete_owned.return_value = False
    service = TaskService(repo)

    with pytest.raises(NotFoundError) as exc:
        await service.delete_task(task_id, owner_id)

    assert exc.value.status_code == 404
    repo.delete_owned.assert_awaited_once_with(task_id, owner_id)
