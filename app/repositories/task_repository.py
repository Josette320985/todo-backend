from collections.abc import Sequence

from fastapi import Depends
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.task import Task


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
        Return the tasks of one user.

        limit=None returns every task (current behaviour). Pagination
        (SEG-H12) and a deterministic order (OPT-02) are added here.
        """
        query: Select[tuple[Task]] = select(Task).where(Task.owner_id == owner_id)
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

        The refresh is kept for now; OPT-03 removes it.
        """
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def delete_owned(self, task_id: int, owner_id: int) -> bool:
        """
        Delete the task if it belongs to owner_id.

        Returns False when there is nothing to delete (missing or someone
        else's task). Still a SELECT + DELETE; OPT-04 makes it one query.
        """
        task = await self.get_owned(task_id, owner_id)
        if task is None:
            return False
        await self.db.delete(task)
        await self.db.commit()
        return True


def get_task_repository(db: AsyncSession = Depends(get_db)) -> TaskRepository:
    """FastAPI dependency: a TaskRepository bound to the request's session."""
    return TaskRepository(db)
