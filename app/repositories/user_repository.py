from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User


class UserRepository:
    """Data access for users (ARQ-02)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        """Save a new or modified user and return it with its current values."""
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    """FastAPI dependency: a UserRepository bound to the request's session."""
    return UserRepository(db)
