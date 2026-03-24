"""SQLAlchemy declarative base shared by all ORM models.

Usage:
    from src.db.base import Base

    class MyModel(Base):
        __tablename__ = "my_table"
        ...
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All ORM model classes should inherit from this base so that Alembic
    autogenerate can discover the full schema in one pass.
    """
