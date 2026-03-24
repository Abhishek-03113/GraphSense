"""Database configuration loaded from environment variables via pydantic-settings."""

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Settings for the PostgreSQL connection pool."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres DSN — e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_DSN: PostgresDsn

    # Pool sizing — async SQLAlchemy default pool class is AsyncAdaptedQueuePool
    DB_POOL_SIZE: int = 10          # number of persistent connections
    DB_MAX_OVERFLOW: int = 20       # extra connections allowed above pool_size
    DB_POOL_TIMEOUT: int = 30       # seconds to wait for a connection from the pool
    DB_POOL_RECYCLE: int = 1800     # recycle connections older than 30 min
    DB_ECHO: bool = False           # set True to log SQL statements

    @field_validator("DATABASE_DSN", mode="before")
    @classmethod
    def _ensure_asyncpg_scheme(cls, v: str) -> str:
        """Coerce postgresql:// → postgresql+asyncpg:// if the driver is omitted."""
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


# Module-level singleton — imported by engine.py
db_settings = DatabaseSettings()  # type: ignore[call-arg]
