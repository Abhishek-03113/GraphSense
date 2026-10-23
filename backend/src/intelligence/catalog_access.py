"""Where the Ask pipeline gets its catalog snapshot.

The pipeline depends on the one-method :class:`CatalogSource`.  The application uses the
catalog service (stored build, live profile or package fallback, see ``src.catalog.service``).
:class:`PackageCatalogSource` (package only: no row counts or profile statistics) is kept for
tests and tools that run without a database.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any, Protocol

from src.catalog import CatalogSnapshot
from src.datasets.context import DatasetContext


class CatalogSource(Protocol):
    async def get_snapshot(self, ctx: DatasetContext) -> CatalogSnapshot: ...


class PackageCatalogSource:
    """Snapshots built from the package only, cached per package content hash."""

    def __init__(self) -> None:
        self._cache: dict[str, CatalogSnapshot] = {}

    async def get_snapshot(self, ctx: DatasetContext) -> CatalogSnapshot:
        key = ctx.package.content_hash
        snap = self._cache.get(key)
        if snap is None:
            snap = CatalogSnapshot.from_package(ctx.package)
            self._cache = {key: snap}
        return snap


def sensitive_columns(snapshot: CatalogSnapshot) -> frozenset[tuple[str, str]]:
    """``(table, column)`` of every column marked ``sensitive``.

    Uses ``snapshot.sensitive_columns()`` when the catalog provides it, otherwise reads the flags.
    """
    method = getattr(snapshot, "sensitive_columns", None)
    if callable(method):
        return frozenset(method())
    return frozenset((t.name, c.name) for t in snapshot.tables for c in t.columns if c.sensitive)


def llm_safe(snapshot: CatalogSnapshot) -> CatalogSnapshot:
    """A copy of the snapshot that may be shown to a language model.

    Sensitive columns keep their name, type and description (the model needs the schema to write
    queries) but lose every value: min, max, top values, samples and value labels.  Every prompt,
    knowledge item and provider payload is built from this view, never from the raw snapshot.
    Prefers ``snapshot.llm_safe_view()`` when the catalog provides it.
    """
    method = getattr(snapshot, "llm_safe_view", None)
    if callable(method):
        return method()
    tables = []
    for table in snapshot.tables:
        columns = tuple(
            dataclasses.replace(
                c, min_value=None, max_value=None, top_values=(), sample_values=(), value_labels={}
            )
            if c.sensitive
            else c
            for c in table.columns
        )
        tables.append(dataclasses.replace(table, columns=columns))
    return dataclasses.replace(snapshot, tables=tuple(tables))


class ServiceCatalogSource:
    """Adapter for ``get_catalog_service().get_snapshot(dataset_id)``; sync or async."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def get_snapshot(self, ctx: DatasetContext) -> CatalogSnapshot:
        result = self._service.get_snapshot(ctx.id)
        if inspect.isawaitable(result):
            result = await result
        return result


def build_catalog_source() -> CatalogSource:
    """The source used by the application: the catalog service."""
    from src.catalog.service import get_catalog_service

    return ServiceCatalogSource(get_catalog_service())


def catalog_source_for(engine: Any, package: Any = None) -> CatalogSource:
    """A catalog source that reads through ``engine`` instead of the process-wide one.

    ``package`` (when given) is used as the dataset's package instead of looking it up by id.

    For code that runs on its own event loop (an ingestion hook runs in a worker thread): the
    process-wide application engine must only ever be created on the server's loop.
    """
    from src.catalog.service import CatalogService

    if package is None:
        return ServiceCatalogSource(CatalogService(engine=engine))
    return ServiceCatalogSource(CatalogService(engine=engine, package_resolver=lambda _dataset_id: package))
