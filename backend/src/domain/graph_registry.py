"""Selects the active graph dataset.

The dataset is chosen by the ``GRAPH_DATASET`` setting (default ``o2c``) and
resolved to ``src/domain/datasets/<name>.py``, which must expose a module level
``DATASET``.  The result is cached for the life of the process.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from functools import lru_cache

from src.domain import datasets as _datasets_pkg
from src.domain.config import graph_settings
from src.domain.graph_schema import GraphDataset

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class UnknownDatasetError(ValueError):
    """Raised when GRAPH_DATASET does not name a loadable dataset module."""


def available_datasets() -> list[str]:
    """Dataset ids that can be selected via ``GRAPH_DATASET``."""
    return sorted(m.name for m in pkgutil.iter_modules(_datasets_pkg.__path__))


def load_dataset(name: str) -> GraphDataset:
    """Import ``src.domain.datasets.<name>`` and return its ``DATASET``."""
    if not _NAME.match(name) or name not in available_datasets():
        raise UnknownDatasetError(
            f"Unknown graph dataset {name!r}. Available: {', '.join(available_datasets())}"
        )
    module = importlib.import_module(f"{_datasets_pkg.__name__}.{name}")
    dataset = getattr(module, "DATASET", None)
    if not isinstance(dataset, GraphDataset):
        raise UnknownDatasetError(f"Dataset module {name!r} does not define a GraphDataset DATASET")
    if dataset.id != name:
        raise UnknownDatasetError(
            f"Dataset module {name!r} declares id {dataset.id!r}; the two must match"
        )
    return dataset


@lru_cache(maxsize=1)
def _active() -> GraphDataset:
    return load_dataset(graph_settings.GRAPH_DATASET)


def get_dataset(name: str | None = None) -> GraphDataset:
    """The active dataset, or the named one when ``name`` is given."""
    return load_dataset(name) if name else _active()
