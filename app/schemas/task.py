from datetime import date

from pydantic import BaseModel, Field, model_validator


def _check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValueError(
            "La fecha de término no puede ser anterior a la fecha de inicio"
        )


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        _check_dates(self.start_date, self.end_date)
        return self


class TaskUpdate(BaseModel):
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
    id: int
    title: str
    description: str | None
    completed: bool
    start_date: date | None
    end_date: date | None

    model_config = {"from_attributes": True}