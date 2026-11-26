"""
TEST-04: Pure unit tests for date range validation on partial updates.

TaskService.update_task combines the fields in TaskUpdate with the stored Task
values. The TaskRepository is mocked with AsyncMock so all 18 cases run without
opening a SQLite database.
"""

from datetime import date
from typing import Any
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.dates import DATE_RANGE_ERROR
from app.core.errors import ValidationFailed
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskUpdate
from app.services.task_service import TaskService

D1 = date(2026, 11, 1)
D5 = date(2026, 11, 5)
D10 = date(2026, 11, 10)
D15 = date(2026, 11, 15)

Dates = tuple[date | None, date | None]


def _make_mock_service(stored_task: Task) -> tuple[TaskService, MagicMock]:
    repo = MagicMock(spec=TaskRepository)
    repo.get_owned = AsyncMock(return_value=stored_task)
    repo.add = AsyncMock(side_effect=lambda task: task)
    return TaskService(repo), repo


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
    stored: Dates,
    update: dict[str, Any],
    expected: Dates | None,
) -> None:
    owner_id = uuid.uuid4()
    task = Task(
        id=uuid.uuid4(),
        owner_id=owner_id,
        title="Con fechas",
        start_date=stored[0],
        end_date=stored[1],
    )
    service, repo = _make_mock_service(task)
    payload = TaskUpdate.model_validate(update)

    if expected is None:
        with pytest.raises(ValidationFailed) as exc:
            await service.update_task(task.id, owner_id, payload)
        assert exc.value.status_code == 422
        assert [(e.field, e.message) for e in exc.value.errors] == [
            ("end_date", DATE_RANGE_ERROR)
        ]
        repo.add.assert_not_awaited()
        return

    updated = await service.update_task(task.id, owner_id, payload)
    assert (updated.start_date, updated.end_date) == expected
    repo.add.assert_awaited_once_with(task)


async def test_rejected_update_leaves_the_stored_dates() -> None:
    owner_id = uuid.uuid4()
    task = Task(
        id=uuid.uuid4(),
        owner_id=owner_id,
        title="Con fechas",
        start_date=D5,
        end_date=D10,
    )
    service, repo = _make_mock_service(task)

    with pytest.raises(ValidationFailed):
        await service.update_task(
            task.id, owner_id, TaskUpdate(title="Nuevo", end_date=D1)
        )

    repo.add.assert_not_awaited()
    assert (task.title, task.start_date, task.end_date) == ("Con fechas", D5, D10)
