from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for all ORM models and Alembic migrations."""
