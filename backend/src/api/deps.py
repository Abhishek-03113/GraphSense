"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Header, HTTPException, Query

from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import default_dataset_id, get_package

DATASET_HEADER = "X-GraphSense-Dataset"


async def get_dataset_context(
    dataset_header: str | None = Header(default=None, alias=DATASET_HEADER),
    dataset: str | None = Query(default=None, description="Dataset id (default: the deployment's default dataset)"),
) -> DatasetContext:
    """The dataset a request is about: ``X-GraphSense-Dataset`` header, ``?dataset=``, or the default.

    An unknown id answers 404.  Until a database has been adopted into
    per-dataset schemas, ``schema_name`` is ``None`` and the tables are read
    from the legacy ``public`` schema.
    """
    dataset_id = dataset_header or dataset or default_dataset_id()
    try:
        package = get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    return DatasetContext(id=package.id, schema_name=None, package=package)
