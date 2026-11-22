from collections.abc import Sequence
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_current_user, get_task_service
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import TaskService

# Router responsible for authenticated task management.
router: Final[APIRouter] = APIRouter(prefix="/tasks", tags=["tasks"])

# SQLite stores INTEGER as a signed 64-bit value. A larger id overflows the
# driver and would answer 500, so Path rejects it with 422 before the query
# runs. The lower bound also rejects ids that can never exist (SEG-H06).
TaskId = Annotated[int, Path(ge=1, le=2**63 - 1)]


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


@router.patch("/{task_id}", response_model=TaskRead, operation_id="patch_task")
@router.put(
    "/{task_id}",
    response_model=TaskRead,
    operation_id="put_task",
    deprecated=True,
)
async def update_task(
    task_id: TaskId,
    payload: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    Apply a partial update to a task belonging to the authenticated user.

    PATCH is the canonical method. PUT remains a deprecated alias until the
    frontend migrates; both run the same TaskService use case.

    Only allowlisted fields explicitly provided in the request are updated,
    and the resulting start/end date range is validated against existing values.

    Args:
        task_id (TaskId): ID of the task to update. It must fit SQLite's
            signed 64-bit range (1 to 2**63 - 1).
        payload (TaskUpdate): Task fields to modify.
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        Task: The updated task.

    Raises:
        NotFoundError: If the task does not exist or belongs to someone else (404).
        ValidationFailed: If the resulting date range is invalid (422).
        RequestValidationError: If the task id is out of range or the payload
            is invalid (422).
    """
    return await service.update_task(task_id, current_user.id, payload)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: TaskId,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a task belonging to the authenticated user.

    Args:
        task_id (TaskId): ID of the task to delete. It must fit SQLite's
            signed 64-bit range (1 to 2**63 - 1).
        service (TaskService): Task use cases.
        current_user (User): Currently authenticated user.

    Returns:
        None: Successful deletion responds with HTTP 204 No Content.

    Raises:
        NotFoundError: If the task does not exist or is not owned
            by the authenticated user (404).
        RequestValidationError: If the task id is out of range (422).
    """
    await service.delete_task(task_id, current_user.id)
