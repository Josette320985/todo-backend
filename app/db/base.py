from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    Provides shared declarative mapping and metadata
    used to define and create database tables.
    """
    pass
