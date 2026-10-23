"""Finding and reading the source files of a dataset.

The data root is operator configuration (``DATA_ROOT`` or the CLI's
``--data-root``); a package only contributes *relative* locations.  Every
location is resolved (symlinks followed) and must stay inside the data root, so
neither a package nor a symlink inside the data can make the loader read
somewhere else.  Files are read in sorted name order, which makes "last record
wins" deterministic.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.datasets.models import DatasetPackage, TableSpec
from src.ingestion.report import IngestError

SOURCE_SUFFIX = ".jsonl"


@dataclass(frozen=True)
class SourceFile:
    table: str
    name: str  # file name only
    relative: str  # path relative to the dataset's source directory
    path: Path
    size: int


def resolve_data_root(root: Path | str | None) -> Path:
    """The configured data root as an existing, resolved directory."""
    if root is None or str(root).strip() == "":
        raise IngestError("data_root_not_configured", "The data root is not configured (set DATA_ROOT).")
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise IngestError("data_root_missing", "The configured data root is not a directory.")
    return path


def _contained(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def resolve_source_dir(data_root: Path, package: DatasetPackage) -> Path:
    """``<data_root>/<package source subdirectory>``, checked to lie inside the data root."""
    root = data_root.resolve()
    base = (root / package.source.default_subdir).resolve()
    if not _contained(base, root):
        raise IngestError("path_outside_data_root", "The dataset's source location is outside the data root.")
    if not base.is_dir():
        raise IngestError("source_missing", "The dataset's source directory does not exist under the data root.")
    return base


def table_files(base: Path, data_root: Path, table: TableSpec) -> list[SourceFile] | None:
    """The ``*.jsonl`` files of a table in sorted order, or ``None`` when its directory is missing."""
    root = data_root.resolve()
    directory = (base / table.source.path).resolve()
    if not _contained(directory, root):
        raise IngestError(
            "path_outside_data_root", f"Table {table.table}: its source location is outside the data root."
        )
    if not directory.is_dir():
        return None
    files: list[SourceFile] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(SOURCE_SUFFIX):
            continue
        resolved = entry.resolve()
        if not resolved.is_file():
            continue
        if not _contained(resolved, root):
            raise IngestError(
                "path_outside_data_root", f"Table {table.table}: a source file is outside the data root."
            )
        files.append(
            SourceFile(table.table, entry.name, f"{table.source.path}/{entry.name}", resolved, resolved.stat().st_size)
        )
    return files


@dataclass
class Problem:
    code: str  # invalid_json | not_an_object | invalid_encoding
    message: str


def read_records(path: Path, digest: Any = None) -> Iterator[tuple[int, dict[str, Any] | None, Problem | None]]:
    """Yield ``(line number, record, problem)`` for every non-blank line of a JSON Lines file.

    Exactly one of ``record`` and ``problem`` is set.  ``digest`` (a hashlib
    object) is fed every byte read, so the caller can check that the file is the
    one that was fingerprinted.
    """
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, start=1):
            if digest is not None:
                digest.update(raw)
            if not raw.strip():
                continue
            try:
                text = raw.decode("utf-8-sig" if number == 1 else "utf-8")
            except UnicodeDecodeError:
                yield number, None, Problem("invalid_encoding", "the line is not valid UTF-8")
                continue
            try:
                value = json.loads(text)
            except ValueError:
                yield number, None, Problem("invalid_json", "the line is not valid JSON")
                continue
            if not isinstance(value, dict):
                yield number, None, Problem("not_an_object", "the line is not a JSON object")
                continue
            yield number, value, None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
