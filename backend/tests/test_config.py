"""Settings are lazy, typed and never leak secrets."""

import subprocess
import sys
from pathlib import Path

import pytest

from src.config import Settings, dsn_host, get_settings, override_settings, reset_settings

BACKEND = Path(__file__).resolve().parents[1]


def test_importing_the_app_without_any_database_setting_does_not_raise(tmp_path):
    """Run in a clean process: no DSN in the environment, neutral working directory."""
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND), "HOME": str(tmp_path)}
    code = (
        "import src.main, src.db.session, src.db.engine, src.ingestion.runner, src.storage.session\n"
        "from src.config import get_settings\n"
        "print('ok', get_settings().DEFAULT_DATASET)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], check=False, env=env, cwd=tmp_path, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


def test_missing_dsn_is_only_an_error_when_the_database_is_used(monkeypatch):
    monkeypatch.delenv("DATABASE_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings()
    settings = Settings(_env_file=None)
    assert settings.DATABASE_DSN is None
    with pytest.raises(RuntimeError, match="DATABASE_DSN"):
        settings.require_database_dsn()


def test_database_url_is_an_alias_and_gets_the_asyncpg_driver(monkeypatch):
    monkeypatch.delenv("DATABASE_DSN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/app")
    assert str(Settings(_env_file=None).DATABASE_DSN) == "postgresql+asyncpg://u:p@db:5432/app"
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db:5432/app")
    assert str(Settings(_env_file=None).DATABASE_DSN).startswith("postgresql+asyncpg://")


def test_default_dataset_accepts_the_old_name(monkeypatch):
    assert Settings(_env_file=None).DEFAULT_DATASET == "o2c"
    monkeypatch.setenv("GRAPH_DATASET", "toy")
    assert Settings(_env_file=None).DEFAULT_DATASET == "toy"
    monkeypatch.setenv("DEFAULT_DATASET", "other")
    assert Settings(_env_file=None).DEFAULT_DATASET == "other"


def test_embedding_model_accepts_the_old_name(monkeypatch):
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "text-embedding-001")
    assert Settings(_env_file=None).EMBEDDING_MODEL == "text-embedding-001"


def test_lists_accept_comma_separated_values(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("POST_INGEST_HOOKS", "pkg.mod:one,pkg.mod:two")
    settings = Settings(_env_file=None)
    assert settings.CORS_ALLOW_ORIGINS == ["https://a.example", "https://b.example"]
    assert settings.POST_INGEST_HOOKS == ["pkg.mod:one", "pkg.mod:two"]
    monkeypatch.setenv("POST_INGEST_HOOKS", '["x:y"]')
    assert Settings(_env_file=None).POST_INGEST_HOOKS == ["x:y"]


def test_cors_wildcard_is_dev_only(monkeypatch):
    assert Settings(_env_file=None).cors_origins() == ["*"]
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("GRAPHSENSE_ENV", "production")
    assert Settings(_env_file=None).cors_origins() == []
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://app.example,*")
    assert Settings(_env_file=None).cors_origins() == ["https://app.example"]


def test_secrets_are_not_shown_in_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-very-secret")
    monkeypatch.setenv("GRAPHSENSE_ADMIN_TOKEN", "admin-secret")
    settings = Settings(_env_file=None)
    assert "sk-very-secret" not in repr(settings) and "admin-secret" not in repr(settings)
    assert settings.GEMINI_API_KEY.get_secret_value() == "sk-very-secret"


def test_dsn_host_hides_credentials():
    assert dsn_host("postgresql+asyncpg://user:pw@db.example:5432/app") == "db.example:5432/app"


def test_override_settings_applies_and_restores():
    before = get_settings().DEFAULT_DATASET
    with override_settings(DEFAULT_DATASET="zzz") as patched:
        assert get_settings() is patched
        assert get_settings().DEFAULT_DATASET == "zzz"
    assert get_settings().DEFAULT_DATASET == before


def test_legacy_shims_read_the_new_settings(monkeypatch):
    from src.ai.config import ai_settings
    from src.db.config import db_settings
    from src.domain.config import graph_settings

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    reset_settings()
    assert ai_settings.GEMINI_API_KEY == "k"
    assert "localhost" in str(db_settings.DATABASE_DSN)
    assert graph_settings.GRAPH_DATASET == "o2c"
