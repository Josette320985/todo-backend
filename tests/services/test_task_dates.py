"""
TEST-04: date range of a partial update, against the stored values.

The schema only sees the fields of the request; TaskService.update_task
combines them with what is already saved. Each row stores a task, sends a
partial update and checks the resulting range, or the 422 on end_date.
"""

from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.dates import DATE_RANGE_ERROR
from app.core.errors import ValidationFailed
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_service import TaskService
from conftest import TestUser

D1 = date(2026, 11, 1)
D5 = date(2026, 11, 5)
D10 = date(2026, 11, 10)
D15 = date(2026, 11, 15)

Dates = tuple[date | None, date | None]


@pytest.mark.parametrize(
    ("stored", "update", "expected"),
    [
        # Nothing stored.
        pytest.param((None, None), {"start_date": D10}, (D10, None), id="none+start"),
        pytest.param((None, None), {"end_date": D10}, (None, D10), id="none+end"),
        pytest.param(
            (None, None), {"start_date": D1, "end_date": D10}, (D1, D10), id="none+both"
        ),
        # Only a start stored.
        pytest.param((D10, None), {"end_date": D15}, (D10, D15), id="start+later-end"),
        pytest.param((D10, None), {"end_date": D10}, (D10, D10), id="start+same-end"),
        pytest.param((D10, None), {"end_date": D1}, None, id="start+earlier-end"),
        pytest.param(
            (D10, None),
            {"start_date": D1, "end_date": D5},
            (D1, D5),
            id="start+both-replaced",
        ),
        # Only an end stored.
        pytest.param((None, D10), {"start_date": D5}, (D5, D10), id="end+earlier-start"),
        pytest.param((None, D10), {"start_date": D15}, None, id="end+later-start"),
        # Both stored.
        pytest.param((D1, D10), {"end_date": D5}, (D1, D5), id="both+end-inside"),
        pytest.param((D1, D10), {"start_date": D5}, (D5, D10), id="both+start-inside"),
        pytest.param((D1, D10), {"start_date": D15}, None, id="both+start-after-end"),
        pytest.param((D5, D10), {"end_date": D1}, None, id="both+end-before-start"),
        pytest.param(
            (D5, D10), {"start_date": None}, (None, D10), id="both+clear-start"
        ),
        pytest.param((D5, D10), {"end_date": None}, (D5, None), id="both+clear-end"),
        pytest.param(
            (D5, D10),
            {"start_date": None, "end_date": D1},
            (None, D1),
            id="both+clear-start-earlier-end",
        ),
        pytest.param(
            (D1, D10), {"title": "Otro"}, (D1, D10), id="both+no-date-fields"
        ),
    ],
)
async def test_partial_update_checks_the_resulting_range(
    app: FastAPI,
    user: TestUser,
    stored: Dates,
    update: dict[str, Any],
    expected: Dates | None,
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        task = await service.create_task(
            user.id,
            TaskCreate(title="Con fechas", start_date=stored[0], end_date=stored[1]),
        )
        payload = TaskUpdate.model_validate(update)

        if expected is None:
            with pytest.raises(ValidationFailed) as exc:
                await service.update_task(task.id, user.id, payload)
            assert exc.value.status_code == 422
            assert [(e.field, e.message) for e in exc.value.errors] == [
                ("end_date", DATE_RANGE_ERROR)
            ]
            return

        updated = await service.update_task(task.id, user.id, payload)
        assert (updated.start_date, updated.end_date) == expected


async def test_rejected_update_leaves_the_stored_dates(
    app: FastAPI, user: TestUser
) -> None:
    async with app.state.session_factory() as db:
        service = TaskService(TaskRepository(db))
        task = await service.create_task(
            user.id, TaskCreate(title="Con fechas", start_date=D5, end_date=D10)
        )

        with pytest.raises(ValidationFailed):
            await service.update_task(
                task.id, user.id, TaskUpdate(title="Nuevo", end_date=D1)
            )

    async with app.state.session_factory() as db:
        [saved] = await TaskService(TaskRepository(db)).list_tasks(user.id)
        assert (saved.title, saved.start_date, saved.end_date) == ("Con fechas", D5, D10)
