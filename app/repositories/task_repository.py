from collections.abc import Sequence
from typing import Any, Final, cast

from fastapi import Depends
from sqlalchemy import ColumnElement, CursorResult, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.utils.task_sorting import (
    DEFAULT_SORT_ORDER,
    DEFAULT_TASK_SORT,
    SortOrder,
    TaskSortField,
)
from app.db.session import get_db
from app.models.task import Task

# One ORDER BY term: a plain mapped column or an SQL expression.
type OrderClause = ColumnElement[Any] | InstrumentedAttribute[Any]

# Order of GET /tasks (OPT-02): pending first, then by due date with
# undated tasks last, and the id as the final tie-breaker.
TASK_LIST_ORDER = (
    Task.completed,
    Task.end_date.is_(None),
    Task.end_date,
    Task.id,
)

# Allow-list of sortable columns. The ORDER BY is built only from here, never
# from client text. Title is compared case-insensitively.
_SORT_COLUMNS: Final[dict[TaskSortField, OrderClause]] = {
    TaskSortField.COMPLETED: Task.completed,
    TaskSortField.END_DATE: Task.end_date,
    TaskSortField.START_DATE: Task.start_date,
    TaskSortField.TITLE: func.lower(Task.title),
    TaskSortField.ID: Task.id,
}

if set(_SORT_COLUMNS) != set(TaskSortField):
    missing = sorted(set(TaskSortField) - set(_SORT_COLUMNS))
    raise RuntimeError(f"_SORT_COLUMNS has no column for: {missing}")

# Nullable columns: tasks without a value always go last, in both directions.
_NULLABLE_SORT_FIELDS: Final[frozenset[TaskSortField]] = frozenset(
    {TaskSortField.END_DATE, TaskSortField.START_DATE}
)


def build_task_order(
    sort_by: Sequence[TaskSortField] | None = None,
    order: SortOrder = DEFAULT_SORT_ORDER,
) -> tuple[OrderClause, ...]:
    """
    Return the ORDER BY clauses for a task listing (OPT-02).

    The fields are applied in the given sequence, all in the direction
    ``order``; repeated fields are ignored. Without fields the fallback
    DEFAULT_TASK_SORT applies (and ``order`` is ignored), which produces
    ``completed, end_date IS NULL, end_date, id``: the OPT-02 order.
    Tasks with a NULL date always go last, and the id is added as the final
    tie-breaker when the caller did not include it, so the order stays total
    and pagination (SEG-H12) stays stable.
    """
    fields: tuple[TaskSortField, ...] = tuple(dict.fromkeys(sort_by or ()))
    if not fields:
        fields, order = DEFAULT_TASK_SORT, DEFAULT_SORT_ORDER

    clauses: list[OrderClause] = []
    for field in fields:
        column: OrderClause = _SORT_COLUMNS[field]
        if field in _NULLABLE_SORT_FIELDS:
            clauses.append(column.is_(None))
        clauses.append(column.desc() if order is SortOrder.DESC else column.asc())
    if TaskSortField.ID not in fields:
        clauses.append(Task.id)
    return tuple(clauses)


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
        self,
        owner_id: int,
        limit: int | None = None,
        offset: int = 0,
        completed: bool | None = None,
        sort_by: Sequence[TaskSortField] | None = None,
        order: SortOrder = DEFAULT_SORT_ORDER,
    ) -> Sequence[Task]:
        """
        Return the tasks of one user in a deterministic order (OPT-02).

        Without sort_by the OPT-02 order applies: pending tasks first, then
        completed ones; inside each group by due date (tasks without end_date
        last) and finally by id, so two tasks never tie and the order is the
        same on every request. With sort_by, see build_task_order. Pagination
        (SEG-H12) relies on this order. limit=None returns every task;
        completed=None does not filter by status.
        """
        query: Select[tuple[Task]] = (
            select(Task)
            .where(Task.owner_id == owner_id)
            .order_by(*build_task_order(sort_by, order))
        )
        if completed is not None:
            query = query.where(Task.completed == completed)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def count_by_owner(self, owner_id: int) -> int:
        """Number of tasks the user has (SEG-H12 per-user cap)."""
        result = await self.db.execute(
            select(func.count()).select_from(Task).where(Task.owner_id == owner_id)
        )
        return int(result.scalar_one())

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
