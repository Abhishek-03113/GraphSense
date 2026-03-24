"""Database configuration loaded from environment variables via pydantic-settings.

Environment variables are read from the backend/.env file (resolved relative
to this module) and from the process environment.  pydantic-settings handles
all parsing; there is no hand-rolled .env loader.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file relative to *this* source file so it works regardless
# of what the current working directory is when the server starts.
_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
_ENV_FILE = _BACKEND_DIR / ".env"


class DatabaseSettings(BaseSettings):
    """Settings for the PostgreSQL connection pool.

    Reads from (in priority order):
      1. Process environment variables
      2. The ``backend/.env`` file

    The DSN can be supplied as ``DATABASE_DSN`` or ``DATABASE_URL``.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres DSN — e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_DSN: Optional[PostgresDsn] = Field(
        default=None,
        validation_alias="DATABASE_DSN",
    )

    # Pool sizing — async SQLAlchemy default pool class is AsyncAdaptedQueuePool
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    @field_validator("DATABASE_DSN", mode="before")
    @classmethod
    def _coerce_dsn(cls, v: object) -> object:
        """Accept DATABASE_URL as an alias and ensure the asyncpg driver."""
        if v is None:
            return v
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


def _load_settings() -> DatabaseSettings:
    """Build settings, falling back to DATABASE_URL when DATABASE_DSN is absent."""
    import os

    # Attempt primary load
    settings = DatabaseSettings()  # type: ignore[call-arg]

    # Fall back to DATABASE_URL if DATABASE_DSN was not set
    if settings.DATABASE_DSN is None:
        url = os.environ.get("DATABASE_URL")
        if url is not None:
            settings = DatabaseSettings.model_validate({"DATABASE_DSN": url})

    if settings.DATABASE_DSN is None:
        raise RuntimeError(
            f"DATABASE_DSN (or DATABASE_URL) is not set. "
            f"Provide it as an environment variable or in {_ENV_FILE}"
        )

    return settings


# Module-level singleton — imported by engine.py
db_settings: DatabaseSettings = _load_settings()
