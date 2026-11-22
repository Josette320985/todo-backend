"""Business rules for tasks.

The endpoints only authenticate the user and call these methods. Ownership is
still enforced by the repository (a foreign task is reported as missing), and
the resulting date range is validated here because a partial update must be
checked against the values already stored, not only the ones in the request.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any, Final

from app.core.dates import date_range_error
from app.core.errors import NotFoundError, ValidationFailed
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate

# Allowed mutable fields on a Task ORM instance during partial updates.
ALLOWED_UPDATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"title", "description", "completed", "start_date", "end_date"}
)


class TaskService:
    """Task use cases, backed by a TaskRepository."""

    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def list_tasks(self, owner_id: int) -> Sequence[Task]:
        """Return every task owned by the user."""
        return await self._tasks.list_by_owner(owner_id)

    async def create_task(self, owner_id: int, payload: TaskCreate) -> Task:
        """Create a task for the user."""
        task: Task = Task(**payload.model_dump(), owner_id=owner_id)
        return await self._tasks.add(task)

    async def update_task(
        self, task_id: int, owner_id: int, payload: TaskUpdate
    ) -> Task:
        """
        Apply the provided fields to an owned task.

        Args:
            task_id (int): ID of the task to update.
            owner_id (int): ID of the authenticated user.
            payload (TaskUpdate): Fields to modify.

        Returns:
            Task: The updated task.

        Raises:
            NotFoundError: If the task does not exist or belongs to someone else.
            ValidationFailed: If the resulting date range is invalid.
        """
        task: Task | None = await self._tasks.get_owned(task_id, owner_id)
        if task is None:
            raise NotFoundError("Tarea no encontrada")

        updates: dict[str, Any] = payload.model_dump(exclude_unset=True)

        # Validate the resulting range combining stored and updated values.
        new_start: date | None = (
            payload.start_date if "start_date" in updates else task.start_date
        )
        new_end: date | None = (
            payload.end_date if "end_date" in updates else task.end_date
        )
        message: str | None = date_range_error(new_start, new_end)
        if message is not None:
            raise ValidationFailed("end_date", message)

        # Apply only allowlisted fields included in the request.
        for field_name, value in updates.items():
            if field_name in ALLOWED_UPDATE_FIELDS:
                setattr(task, field_name, value)

        return await self._tasks.add(task)

    async def delete_task(self, task_id: int, owner_id: int) -> None:
        """
        Delete an owned task.

        Raises:
            NotFoundError: If the task does not exist or belongs to someone else.
        """
        if not await self._tasks.delete_owned(task_id, owner_id):
            raise NotFoundError("Tarea no encontrada")
