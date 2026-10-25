"""Selects the active graph dataset.

Graph definitions are not code: they come from dataset packages (see
``src/datasets``).  The dataset used when a request does not name one is the
``DEFAULT_DATASET`` setting.  Packages are loaded and validated once and cached.
"""

from __future__ import annotations

from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import available_ids, default_dataset_id, get_package
from src.domain.graph_schema import GraphDataset

__all__ = ["UnknownDatasetError", "available_datasets", "get_dataset", "load_dataset"]


def available_datasets() -> list[str]:
    """Ids of the dataset packages that can be selected."""
    return available_ids()


def load_dataset(name: str) -> GraphDataset:
    """The graph model of dataset package ``name``."""
    return get_package(name).graph_dataset()


def get_dataset(name: str | None = None) -> GraphDataset:
    """The graph model of the named dataset, or of the default dataset."""
    return load_dataset(name or default_dataset_id())
