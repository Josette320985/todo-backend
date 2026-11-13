from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Create the asynchronous database engine using the configured URL.
engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

# Configure a factory for creating asynchronous database sessions.
# Keep ORM objects accessible after committing a transaction.
AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db():
    """
    Provide an asynchronous database session for FastAPI dependencies.

    Creates a database session for the request and automatically
    closes it when the dependency finishes.

    Yields:
        AsyncSession: Active asynchronous database session.
    """
    async with AsyncSessionLocal() as session:
        yield session
