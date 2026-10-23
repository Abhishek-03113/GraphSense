"""Application settings: one place, built lazily.

``get_settings()`` builds the :class:`Settings` on first use and caches it, so
importing the application never needs a database DSN or any other value.  A
setting is read from, in priority order, the process environment and
``backend/.env``.

Tests override values with :func:`override_settings`, or call
:func:`reset_settings` after changing the environment.

Secrets (``GEMINI_API_KEY``, ``GRAPHSENSE_ADMIN_TOKEN``) are ``SecretStr`` and
must be unwrapped explicitly with ``get_secret_value()``; ``repr`` and logs
never show them.  Use :func:`dsn_host` when a DSN has to appear in a log line.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
_ENV_FILE = BACKEND_DIR / ".env"


def _csv(value: object) -> object:
    """Accept ``a,b`` as well as a JSON list for list settings."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- environment ----------------------------------------------------
    GRAPHSENSE_ENV: Literal["dev", "production"] = "dev"
    LOG_LEVEL: str = "INFO"

    # --- database -------------------------------------------------------
    # postgresql+asyncpg://user:pass@host:5432/db (DATABASE_URL is accepted too).
    DATABASE_DSN: PostgresDsn | None = Field(
        default=None, validation_alias=AliasChoices("DATABASE_DSN", "DATABASE_URL")
    )
    # Role used for LLM-generated SQL only (SELECT-only).
    READONLY_DATABASE_DSN: PostgresDsn | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # --- datasets -------------------------------------------------------
    # Dataset used when a request does not name one.  GRAPH_DATASET is the old name.
    DEFAULT_DATASET: str = Field(
        default="o2c", validation_alias=AliasChoices("DEFAULT_DATASET", "GRAPH_DATASET")
    )
    # Extra directory holding dataset packages (<id>/package.yaml), searched
    # before the packages shipped in the repository.
    PACKAGES_DIR: Path | None = None
    # Directory the operator keeps source data in; a package names a subdirectory of it.
    DATA_ROOT: Path | None = None

    # --- operator access ------------------------------------------------
    GRAPHSENSE_ADMIN_TOKEN: SecretStr | None = None

    # --- models ---------------------------------------------------------
    LLM_PROVIDER: str = "gemini"
    EMBEDDING_PROVIDER: str = "gemini"
    GEMINI_API_KEY: SecretStr = SecretStr("")
    GEMINI_MODEL: str = "gemini-2.0-flash"
    EMBEDDING_MODEL: str = Field(
        default="text-embedding-004",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "GEMINI_EMBEDDING_MODEL"),
    )

    # --- generated SQL limits -------------------------------------------
    SQL_MAX_ROWS: int = Field(default=200, ge=1)
    SQL_STATEMENT_TIMEOUT_MS: int = Field(default=5000, ge=1)

    # --- web ------------------------------------------------------------
    # Comma separated origins.  Empty means "*" in dev and none in production.
    CORS_ALLOW_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # 0 disables the limiter.
    CHAT_RATE_LIMIT_PER_MIN: int = Field(default=0, ge=0)

    # --- ingestion / catalog --------------------------------------------
    # Dotted paths ("module:attr") of hooks run around the dataset swap.
    POST_INGEST_HOOKS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    PROFILE_SAMPLE_ROWS: int = Field(default=50000, ge=1)
    ENUM_MAX_DISTINCT: int = Field(default=50, ge=1)

    @field_validator("CORS_ALLOW_ORIGINS", "POST_INGEST_HOOKS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        return _csv(v)

    @field_validator("DATABASE_DSN", "READONLY_DATABASE_DSN", mode="before")
    @classmethod
    def _asyncpg_driver(cls, v: object) -> object:
        """Plain ``postgresql://`` (as Railway and Heroku provide) means the asyncpg driver here."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("GRAPHSENSE_ENV", mode="before")
    @classmethod
    def _lower_env(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @property
    def is_production(self) -> bool:
        return self.GRAPHSENSE_ENV == "production"

    def cors_origins(self) -> list[str]:
        """Origins allowed by CORS.  ``*`` is never honoured in production."""
        origins = list(self.CORS_ALLOW_ORIGINS)
        if self.is_production:
            return [o for o in origins if o != "*"]
        return origins or ["*"]

    def require_database_dsn(self) -> str:
        """The application DSN, or a clear error when it is not configured."""
        if self.DATABASE_DSN is None:
            raise RuntimeError(
                "DATABASE_DSN (or DATABASE_URL) is not set. "
                f"Provide it as an environment variable or in {_ENV_FILE}"
            )
        return str(self.DATABASE_DSN)


@lru_cache(maxsize=1)
def _build() -> Settings:
    return Settings()


_override: Settings | None = None


def get_settings() -> Settings:
    """The process-wide settings, built on first use and then cached."""
    return _override if _override is not None else _build()


def reset_settings() -> None:
    """Forget the cached settings so the next ``get_settings()`` re-reads the environment."""
    _build.cache_clear()


@contextmanager
def override_settings(**values: object) -> Iterator[Settings]:
    """Use modified settings for the duration of a ``with`` block (tests).

    ``values`` are applied on top of the current settings without re-reading
    the environment; the previous settings are restored on exit.
    """
    global _override
    previous = _override
    patched = get_settings().model_copy(update=values)
    _override = patched
    try:
        yield patched
    finally:
        _override = previous


def dsn_host(dsn: object) -> str:
    """The ``host:port/db`` part of a DSN, safe to log (credentials removed)."""
    return str(dsn).split("@")[-1]
