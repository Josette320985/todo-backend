from datetime import date

from pydantic import BaseModel, Field, model_validator


def _check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValueError(
            "La fecha de término no puede ser anterior a la fecha de inicio"
        )


class TaskCreate(BaseModel):
    """
    Schema for creating a new task.

    Requires a title between 1 and 200 characters and allows
    an optional description of up to 1000 characters.
    """

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        _check_dates(self.start_date, self.end_date)
        return self


class TaskUpdate(BaseModel):
    """
    Schema for updating an existing task.

    Allows partial updates to the title, description,
    or completion status. All fields are optional.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    completed: bool | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        _check_dates(self.start_date, self.end_date)
        return self


class TaskRead(BaseModel):
    """
    Schema for returning task information in API responses.

    Includes the task identifier, title, description,
    and completion status.
    """

    id: int
    title: str
    description: str | None
    completed: bool
    start_date: date | None
    end_date: date | None

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = {"from_attributes": True}
