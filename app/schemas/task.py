from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """
    Schema for creating a new task.

    Requires a title between 1 and 200 characters and allows
    an optional description of up to 1000 characters.
    """

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class TaskUpdate(BaseModel):
    """
    Schema for updating an existing task.

    Allows partial updates to the title, description,
    or completion status. All fields are optional.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    completed: bool | None = None


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

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = {"from_attributes": True}
