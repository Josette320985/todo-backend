
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

# Router responsible for authenticated task management.
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=list[TaskRead])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve all tasks belonging to the authenticated user.

    Args:
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        list[Task]: Tasks owned by the authenticated user.
    """
    # Filter tasks by the authenticated user's ID.
    result = await db.execute(select(Task).where(Task.owner_id == current_user.id))
    return result.scalars().all()


@router.post("/", response_model=TaskRead, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    task = Task(**payload.model_dump(), owner_id=current_user.id)
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
):
    """
    Update an existing task belonging to the authenticated user.

    Only fields explicitly provided in the request are updated.

    Args:
        task_id (int): ID of the task to update.
        payload (TaskUpdate): Task fields to modify.
        db (AsyncSession): Asynchronous database session.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The updated task.

    Raises:
        HTTPException: If the task is not found or is not owned
            by the authenticated user (404).
    """
    # Find the task and verify ownership.
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    # Apply only the fields included in the request.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    # Delete the task and commit the transaction.
    await db.delete(task)
    await db.commit()
