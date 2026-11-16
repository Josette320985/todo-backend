from collections.abc import Sequence
from datetime import date
from typing import Final

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

# Router responsible for authenticated task management.
router: Final[APIRouter] = APIRouter(prefix="/tasks", tags=["tasks"])

# Allowed mutable fields on a Task ORM instance during partial updates.
ALLOWED_UPDATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"title", "description", "completed", "start_date", "end_date"}
)


@router.get("/", response_model=list[TaskRead])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Sequence[Task]:
    """
    Retrieve all tasks belonging to the authenticated user.

    Args:
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        Sequence[Task]: Tasks owned by the authenticated user.
    """
    # Filter tasks by the authenticated user's ID.
    result: Result[tuple[Task]] = await db.execute(
        select(Task).where(Task.owner_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/", response_model=TaskRead, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    Create a new task for the authenticated user.

    Args:
        payload (TaskCreate): Data required to create the task.
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The newly created task.
    """
    # Associate the new task with the authenticated user.
    task: Task = Task(**payload.model_dump(), owner_id=current_user.id)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.put("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    Update an existing task belonging to the authenticated user.

    Only allowlisted fields explicitly provided in the request are updated,
    and the resulting start/end date range is validated against existing values.

    Args:
        task_id (int): ID of the task to update.
        payload (TaskUpdate): Task fields to modify.
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The updated task.

    Raises:
        HTTPException: If the task is not found (404) or the resulting date
            range is invalid (422).
    """
    # Find the task and verify ownership.
    result: Result[tuple[Task]] = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    )
    task: Task | None = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    updates: dict[str, object] = payload.model_dump(exclude_unset=True)

    # Validate the resulting date range combining existing and updated values.
    new_start: date | None = (
        payload.start_date if "start_date" in updates else task.start_date
    )
    new_end: date | None = (
        payload.end_date if "end_date" in updates else task.end_date
    )
    if new_start and new_end and new_end < new_start:
        raise HTTPException(
            status_code=422,
            detail="La fecha de término no puede ser anterior a la fecha de inicio",
        )

    # Apply only allowlisted fields included in the request.
    for field, value in updates.items():
        if field in ALLOWED_UPDATE_FIELDS:
            setattr(task, field, value)

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a task belonging to the authenticated user.

    Args:
        task_id (int): ID of the task to delete.
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        None: Successful deletion responds with HTTP 204 No Content.

    Raises:
        HTTPException: If the task is not found or is not owned
            by the authenticated user (404).
    """
    # Find the task and verify ownership before deletion.
    result: Result[tuple[Task]] = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    )
    task: Task | None = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    # Delete the task and commit the transaction.
    await db.delete(task)
    await db.commit()
