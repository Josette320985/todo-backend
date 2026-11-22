from collections.abc import Sequence
from typing import Final

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_task_service
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import TaskService

# Router responsible for authenticated task management.
router: Final[APIRouter] = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=list[TaskRead])
async def list_tasks(
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> Sequence[Task]:
    """
    Retrieve all tasks belonging to the authenticated user.

    Args:
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        Sequence[Task]: Tasks owned by the authenticated user.
    """
    return await service.list_tasks(current_user.id)


@router.post("/", response_model=TaskRead, status_code=201)
async def create_task(
    payload: TaskCreate,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    Create a new task for the authenticated user.

    Args:
        payload (TaskCreate): Data required to create the task.
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The newly created task.
    """
    return await service.create_task(current_user.id, payload)


@router.put("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    Update an existing task belonging to the authenticated user.

    Only allowlisted fields explicitly provided in the request are updated,
    and the resulting start/end date range is validated against existing values.

    Args:
        task_id (int): ID of the task to update.
        payload (TaskUpdate): Task fields to modify.
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The updated task.

    Raises:
        NotFoundError: If the task does not exist or belongs to someone else (404).
        ValidationFailed: If the resulting date range is invalid (422).
    """
    return await service.update_task(task_id, current_user.id, payload)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a task belonging to the authenticated user.

    Args:
        task_id (int): ID of the task to delete.
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        None: Successful deletion responds with HTTP 204 No Content.

    Raises:
        NotFoundError: If the task does not exist or is not owned
            by the authenticated user (404).
    """
    await service.delete_task(task_id, current_user.id)
