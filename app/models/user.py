
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Import Task only for static type checking to avoid circular imports.
if TYPE_CHECKING:
    from app.models.task import Task


class User(Base):
    """
    SQLAlchemy model representing a registered application user.

    Stores the user's email and hashed password, and defines
    a one-to-many relationship with their associated tasks.
    """

    __tablename__ = "users"

    # Unique identifier for each user.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=getattr(uuid, "uuid7", uuid.uuid4)
    )

    # Unique email address used for authentication.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Store the password hash instead of the plain-text password.
    hashed_password: Mapped[str] = mapped_column(String(255))

    # "local" checks bcrypt. "ldap" checks the directory and keeps a random
    # hash so the password column stays non-null (F1).
    auth_provider: Mapped[str] = mapped_column(
        String(16), default="local", server_default="local"
    )

    # Embedded in every JWT ("ver" claim). Incrementing it on logout
    # revokes all tokens previously issued to this user.
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")

    # One-to-many relationship with tasks.
    # Deleting a user also deletes their associated tasks.
    # Orphaned tasks are automatically removed.
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
