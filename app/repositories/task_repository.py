from collections.abc import Sequence
from typing import Any, cast

from fastapi import Depends
from sqlalchemy import CursorResult, Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.task import Task


# Order of GET /tasks (OPT-02): pending first, then by due date with
# undated tasks last, and the id as the final tie-breaker.
TASK_LIST_ORDER = (
    Task.completed,
    Task.end_date.is_(None),
    Task.end_date,
    Task.id,
)


class TaskRepository:
    """
    Data access for tasks (ARQ-02).

    Every read and delete is scoped by owner_id: a task that belongs to
    another user is reported exactly like a task that does not exist, so the
    endpoints cannot leak other users' data by forgetting the filter.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_owner(
        self, owner_id: int, limit: int | None = None, offset: int = 0
    ) -> Sequence[Task]:
        """
        Return the tasks of one user in a deterministic order (OPT-02).

        Pending tasks first, then completed ones; inside each group by due
        date (tasks without end_date last) and finally by id, so two tasks
        never tie and the order is the same on every request. Pagination
        (SEG-H12) relies on this order. limit=None returns every task.
        """
        query: Select[tuple[Task]] = (
            select(Task)
            .where(Task.owner_id == owner_id)
            .order_by(*TASK_LIST_ORDER)
        )
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_owned(self, task_id: int, owner_id: int) -> Task | None:
        """Return the task only if it exists and belongs to owner_id."""
        result = await self.db.execute(
            select(Task).where(Task.id == task_id, Task.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def add(self, task: Task) -> Task:
        """
        Save a new or modified task and return it with its current values.

        No refresh after the commit (OPT-03): the session factory uses
        expire_on_commit=False, so the object keeps its values, and the flush
        already fills the generated id and the column defaults (completed).
        A refresh would only repeat that work with an extra SELECT.
        """
        self.db.add(task)
        await self.db.commit()
        return task

    async def delete_owned(self, task_id: int, owner_id: int) -> bool:
        """
        Delete the task if it belongs to owner_id, in a single query (OPT-04).

        The ownership check lives in the WHERE clause, so another user's task
        is simply not matched. Returns False when nothing was deleted (missing
        or someone else's task); the caller answers 404 in both cases.
        """
        result = cast(
            CursorResult[Any],
            await self.db.execute(
                delete(Task).where(Task.id == task_id, Task.owner_id == owner_id)
            ),
        )
        await self.db.commit()
        return result.rowcount > 0


def get_task_repository(db: AsyncSession = Depends(get_db)) -> TaskRepository:
    """FastAPI dependency: a TaskRepository bound to the request's session."""
    return TaskRepository(db)
