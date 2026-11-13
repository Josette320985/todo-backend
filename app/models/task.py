feature/task-dates
from datetime import date


main
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Import User only for static type checking to avoid circular imports.
if TYPE_CHECKING:
    from app.models.user import User


class Task(Base):
    """
    SQLAlchemy model representing a task in the database.

    Each task contains a title, an optional description,
    a completion status, and a reference to its owner.
    """

    __tablename__ = "tasks"

    # Unique identifier and task information.
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), default=None)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    feature/task-dates
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)


    # Foreign key linking the task to its owner.
    main
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # ORM relationship with the User model.
    owner: Mapped["User"] = relationship(back_populates="tasks")
