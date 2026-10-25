"""Application settings: one place, built lazily.

``get_settings()`` builds the :class:`Settings` on first use and caches it, so
importing the application never needs a database DSN or any other value.  A
setting is read from, in priority order, the process environment and
``backend/.env``.

Tests override values with :func:`override_settings`, or call
:func:`reset_settings` after changing the environment.

Secrets (``GEMINI_API_KEY``, ``ADMIN_TOKEN``) are ``SecretStr`` and
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

# Hooks run around the dataset swap when POST_INGEST_HOOKS is not set: the catalog is built
# from the staged data (pre_swap), knowledge items are refreshed once the data is live (post_swap).
DEFAULT_POST_INGEST_HOOKS: tuple[str, ...] = (
    "src.catalog.hooks:refresh_catalog",
    "src.intelligence.knowledge.hooks:refresh_knowledge",
)


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
    # Role that creates schemas and loads data (ingestion, migrations, role setup).
    # Defaults to DATABASE_DSN, so a single-role deployment needs no extra setting.
    OWNER_DATABASE_DSN: PostgresDsn | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # --- datasets -------------------------------------------------------
    # Dataset used when a request does not name one.
    DEFAULT_DATASET: str = "o2c"
    # Extra directory holding dataset packages (<id>/package.yaml), searched
    # before the packages shipped in the repository.
    PACKAGES_DIR: Path | None = None
    # Directory the operator keeps source data in; a package names a subdirectory of it.
    DATA_ROOT: Path | None = None

    # --- operator access ------------------------------------------------
    # Bearer token of the operator API.  Without it the admin routes do not exist.
    # ADMIN_TOKEN is the documented name; GRAPHSENSE_ADMIN_TOKEN is accepted too.
    GRAPHSENSE_ADMIN_TOKEN: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ADMIN_TOKEN", "GRAPHSENSE_ADMIN_TOKEN")
    )

    # --- models ---------------------------------------------------------
    # LLM_PROVIDER / EMBEDDING_PROVIDER: openrouter | openai_compatible | gemini | none
    LLM_PROVIDER: str = "openrouter"
    EMBEDDING_PROVIDER: str = "openrouter"
    # OpenRouter (https://openrouter.ai) and any other OpenAI-compatible server.
    OPENROUTER_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    # For LLM_PROVIDER=openai_compatible: the server's /v1 URL, key and model.
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = "gpt-4o-mini"
    # Reasoning effort for models that think (minimal | low | medium | high); empty = model default.
    LLM_REASONING_EFFORT: str = ""
    EMBEDDING_BASE_URL: str = ""  # empty: the LLM provider's base URL
    EMBEDDING_API_KEY: SecretStr = SecretStr("")  # empty: the LLM provider's key
    GEMINI_API_KEY: SecretStr = SecretStr("")
    GEMINI_MODEL: str = "gemini-2.0-flash"
    EMBEDDING_MODEL: str = Field(
        default="openai/text-embedding-3-small",
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
    # Dotted paths ("module:attr") of hooks run around the dataset swap: the catalog is built
    # before the swap (against the staged data), knowledge items are refreshed after it.
    POST_INGEST_HOOKS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_POST_INGEST_HOOKS)
    )
    PROFILE_SAMPLE_ROWS: int = Field(default=50000, ge=1)
    ENUM_MAX_DISTINCT: int = Field(default=50, ge=1)

    # --- conversational query (Ask) -------------------------------------
    # Vector size to request from the embedding model; None keeps the model's default.
    # The size actually returned is stored with every embedded item.
    EMBEDDING_DIMS: int | None = Field(default=None, ge=1)
    LLM_TIMEOUT_S: float = Field(default=30.0, gt=0)
    # Times a failed query is sent back to the model for repair (syntax, unknown column/table, type).
    SQL_REPAIR_ATTEMPTS: int = Field(default=2, ge=0, le=5)
    # Result rows shown to the model when it writes the answer (never more than SQL_MAX_ROWS).
    SYNTHESIS_MAX_ROWS: int = Field(default=50, ge=1)
    # Size budget of the retrieved context in a prompt, in characters.
    RETRIEVAL_CONTEXT_CHARS: int = Field(default=14000, ge=1000)
    # Questions and generated SQL are kept in app.query_log this long (see ``graphsense knowledge purge-log``).
    QUERY_LOG_ENABLED: bool = True
    QUERY_LOG_RETENTION_DAYS: int = Field(default=90, ge=1)
    # Behind a gateway the client address is in X-Forwarded-For; only trust it when the gateway sets it.
    CHAT_RATE_LIMIT_TRUST_FORWARDED: bool = False

    @field_validator("CORS_ALLOW_ORIGINS", "POST_INGEST_HOOKS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        return _csv(v)

    @field_validator("GRAPHSENSE_ADMIN_TOKEN", "PACKAGES_DIR", "DATA_ROOT", mode="before")
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        """``ADMIN_TOKEN=`` in an env file means "not set", not an empty secret."""
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("DATABASE_DSN", "READONLY_DATABASE_DSN", "OWNER_DATABASE_DSN", mode="before")
    @classmethod
    def _asyncpg_driver(cls, v: object) -> object:
        """Plain ``postgresql://`` (as hosting providers usually give it) means the asyncpg driver here."""
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

    @property
    def admin_enabled(self) -> bool:
        """True when an operator token is configured (and so the admin routes are mounted)."""
        return self.GRAPHSENSE_ADMIN_TOKEN is not None

    def require_owner_dsn(self) -> str:
        """The DSN of the role that owns the schemas: ``OWNER_DATABASE_DSN``, else the application DSN."""
        if self.OWNER_DATABASE_DSN is not None:
            return str(self.OWNER_DATABASE_DSN)
        return self.require_database_dsn()

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
