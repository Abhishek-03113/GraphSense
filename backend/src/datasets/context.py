"""The dataset a request or job works on."""

from __future__ import annotations

from dataclasses import dataclass

from src.datasets.models import DatasetPackage


@dataclass(frozen=True)
class DatasetContext:
    """Which dataset to use, and where its tables live.

    ``schema_name`` is the PostgreSQL schema holding the dataset's tables, or
    ``None`` while the tables still live in the legacy ``public`` schema
    (a database that has not been adopted yet).
    """

    id: str
    schema_name: str | None
    package: DatasetPackage
