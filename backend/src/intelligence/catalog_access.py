"""Where the Ask pipeline gets its catalog snapshot.

The pipeline depends on the one-method :class:`CatalogSource`.  Until the
semantic catalog service (workstream C) is merged the source is built from the
dataset package alone (:class:`PackageCatalogSource`: no row counts or profile
statistics).  Switching to the live catalog is a one-line change in
:func:`build_catalog_source`; nothing else in ``src/intelligence`` changes.
"""

from __future__ import annotations

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


class ServiceCatalogSource:
    """Adapter for ``CatalogService.get_snapshot(dataset_id)`` (workstream C); sync or async."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def get_snapshot(self, ctx: DatasetContext) -> CatalogSnapshot:
        result = self._service.get_snapshot(ctx.id)
        if inspect.isawaitable(result):
            result = await result
        return result


def build_catalog_source() -> CatalogSource:
    """The source used by the application.

    At merge with workstream C, replace the body with::

        from src.catalog.service import CatalogService
        return ServiceCatalogSource(CatalogService())
    """
    return PackageCatalogSource()
