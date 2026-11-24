from datetime import date
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, String, Uuid
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
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), default=None)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)


    # Foreign key linking the task to its owner. Indexed because every
    # task query filters by owner (OPT-01, migration 0003).
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), index=True
    )

    # ORM relationship with the User model.
    owner: Mapped["User"] = relationship(back_populates="tasks")
