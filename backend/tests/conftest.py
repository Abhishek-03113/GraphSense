"""Shared test configuration.

Importing the application needs no database settings (everything is read
lazily; ``tests/test_config.py`` proves it in a clean subprocess).  Requests
that resolve the session dependency do build a session factory, though, so
each test gets a placeholder DSN.  Nothing connects: engines are lazy and the
tests that run queries use recording or scripted sessions.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from src.config import BACKEND_DIR, reset_settings
from src.datasets import load_package
from src.datasets.models import DatasetPackage

FIXTURES = Path(__file__).parent / "fixtures"
TOY_DIR = FIXTURES / "packages" / "toy_library"
TOY_DATA_DIR = FIXTURES / "sources" / "toy-library"
O2C_DIR = BACKEND_DIR / "dataset_packages" / "o2c"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("DATABASE_DSN", "postgresql+asyncpg://user:pass@localhost:5432/unused")
    monkeypatch.delenv("PACKAGES_DIR", raising=False)
    reset_settings()
    yield
    reset_settings()


@pytest.fixture(scope="session")
def toy_package() -> DatasetPackage:
    return load_package(TOY_DIR)


@pytest.fixture(scope="session")
def o2c_package() -> DatasetPackage:
    return load_package(O2C_DIR)


@pytest.fixture
def package_copy(tmp_path: Path) -> Callable[..., Path]:
    """Copy a package into a temp directory, optionally changing files.

    ``edits`` maps a path inside the package to either new text, ``None`` (delete the file), or
    a ``(old, new)`` tuple that replaces one piece of the existing text.
    """

    counter = iter(range(1000))

    def make(source: Path = TOY_DIR, edits: dict | None = None) -> Path:
        target = tmp_path / f"copy{next(counter)}" / source.name
        shutil.copytree(source, target)
        for rel, change in (edits or {}).items():
            file = target / rel
            if change is None:
                file.unlink()
            elif isinstance(change, tuple):
                old, new = change
                text = file.read_text(encoding="utf-8")
                assert old in text, f"{old!r} not found in {rel}"
                file.write_text(text.replace(old, new, 1), encoding="utf-8")
            else:
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(change, encoding="utf-8")
        return target

    return make
