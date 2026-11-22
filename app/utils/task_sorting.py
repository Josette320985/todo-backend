"""Sort options for ``GET /tasks`` (OPT-02 follow-up).

Plain enums with no dependencies, so the router, the service and the
repository can share them without importing each other.
"""

from enum import StrEnum
from typing import Final


class TaskSortField(StrEnum):
    """Field a client may sort the task list by."""

    COMPLETED = "completed"
    END_DATE = "end_date"
    START_DATE = "start_date"
    TITLE = "title"
    ID = "id"


class SortOrder(StrEnum):
    """Direction of a sort."""

    ASC = "asc"
    DESC = "desc"


# Fallback used whenever the client sends no sort_by. It is the OPT-02 order:
# pending first, then by due date (undated last), then id. Clients can send
# this same list explicitly and get the same result.
DEFAULT_TASK_SORT: Final[tuple[TaskSortField, ...]] = (
    TaskSortField.COMPLETED,
    TaskSortField.END_DATE,
    TaskSortField.ID,
)
DEFAULT_SORT_ORDER: Final[SortOrder] = SortOrder.ASC