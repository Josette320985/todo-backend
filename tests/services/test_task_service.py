from datetime import date

import pytest
from fastapi import FastAPI

from app.core.errors import NotFoundError, ValidationFailed
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_service import TaskService
from conftest import TestUser


async def test_create_and_list(app: FastAPI, user: TestUser) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(
            user.id, TaskCreate(title="  Comprar pan  ")
        )
        assert created.id is not None
        assert created.title == "Comprar pan"

        listed = await service.list_tasks(user.id)
        assert [task.id for task in listed] == [created.id]


async def test_list_only_returns_owner_tasks(
    app: FastAPI, user: TestUser, other_user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        mine = await service.create_task(user.id, TaskCreate(title="Mía"))
        await service.create_task(other_user.id, TaskCreate(title="Ajena"))

        assert [task.id for task in await service.list_tasks(user.id)] == [
            mine.id
        ]


async def test_partial_update_keeps_untouched_fields(
    app: FastAPI, user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(
            user.id, TaskCreate(title="Original", description="Detalle")
        )

        updated = await service.update_task(
            created.id, user.id, TaskUpdate(completed=True)
        )

        assert updated.completed is True
        assert updated.title == "Original"
        assert updated.description == "Detalle"


async def test_update_validates_dates_against_stored_values(
    app: FastAPI, user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(
            user.id,
            TaskCreate(title="Con fechas", start_date=date(2026, 11, 10)),
        )

        with pytest.raises(ValidationFailed) as exc:
            await service.update_task(
                created.id, user.id, TaskUpdate(end_date=date(2026, 11, 1))
            )

        assert exc.value.status_code == 422
        assert exc.value.errors[0].field == "end_date"


async def test_update_accepts_valid_range(
    app: FastAPI, user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(
            user.id,
            TaskCreate(
                title="Con fechas",
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 10),
            ),
        )

        updated = await service.update_task(
            created.id, user.id, TaskUpdate(end_date=date(2026, 11, 5))
        )

        assert updated.end_date == date(2026, 11, 5)


async def test_update_missing_task_raises_not_found(
    app: FastAPI, user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))

        with pytest.raises(NotFoundError) as exc:
            await service.update_task(
                999999, user.id, TaskUpdate(title="x")
            )

        assert exc.value.status_code == 404


async def test_other_users_task_is_not_found(
    app: FastAPI, user: TestUser, other_user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(user.id, TaskCreate(title="Mía"))

        with pytest.raises(NotFoundError):
            await service.update_task(
                created.id, other_user.id, TaskUpdate(title="x")
            )
        with pytest.raises(NotFoundError):
            await service.delete_task(created.id, other_user.id)


async def test_delete_owned_task(app: FastAPI, user: TestUser) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        created = await service.create_task(user.id, TaskCreate(title="Borrar"))

        await service.delete_task(created.id, user.id)

        with pytest.raises(NotFoundError):
            await service.delete_task(created.id, user.id)
