"""SQLAlchemy 2.0 models mirroring the Alembic migrations (DESIGN.md §5)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
