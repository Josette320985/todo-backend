from datetime import date
from typing import Self
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.dates import date_range_error


def _check_dates(start: date | None, end: date | None) -> None:
    message: str | None = date_range_error(start, end)
    if message is not None:
        raise ValueError(message)


class TaskCreate(BaseModel):
    """
    Schema for creating a new task.

    Requires a non-blank title between 1 and 200 characters and allows
    an optional description of up to 1000 characters.
    """

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        stripped: str = value.strip()
        if not stripped:
            raise ValueError("El título no puede estar vacío")
        return stripped

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        _check_dates(self.start_date, self.end_date)
        return self


class TaskUpdate(BaseModel):
    """
    Schema for updating an existing task.

    Allows partial updates to the title, description,
    or completion status. Explicitly passing null for non-nullable
    database columns ('title' or 'completed') is rejected.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    completed: bool | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped: str = value.strip()
        if not stripped:
            raise ValueError("El título no puede estar vacío")
        return stripped

    @model_validator(mode="after")
    def validate_dates_and_non_null_fields(self) -> Self:
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("El título no puede ser nulo")
        if "completed" in self.model_fields_set and self.completed is None:
            raise ValueError("El estado 'completed' no puede ser nulo")
        _check_dates(self.start_date, self.end_date)
        return self


class TaskRead(BaseModel):
    """
    Schema for returning task information in API responses.

    Includes the task identifier, title, description,
    and completion status.
    """

    id: uuid.UUID
    title: str
    description: str | None
    completed: bool
    start_date: date | None
    end_date: date | None

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = ConfigDict(from_attributes=True)
