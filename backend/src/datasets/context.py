"""The dataset a request or job works on."""

from __future__ import annotations

from dataclasses import dataclass

from src.datasets.models import DatasetPackage


@dataclass(frozen=True)
class DatasetContext:
    """Which dataset to use, and where its tables live.

    ``schema_name`` is the PostgreSQL schema holding the dataset's tables (``ds_<id>``).
    """

    id: str
    schema_name: str
    package: DatasetPackage
