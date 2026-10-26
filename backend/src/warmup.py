"""Work done once at startup so the first requests do not pay for it.

Loading and validating a dataset package (YAML, generated SQL checks) takes most of a
second; it happens before the server accepts requests.  Opening the first database
connection and reading each dataset's catalog happen in the background, so a slow or
absent database never delays startup; a request that comes first simply does that work
itself, as before.
"""

from __future__ import annotations

import asyncio
import time

from src.datasets.context import DatasetContext
from src.datasets.errors import PackageError
from src.datasets.registry import get_package, list_packages
from src.utils.logger import get_logger

logger = get_logger(__name__)

DATABASE_WARMUP_TIMEOUT_S = 15.0


def load_packages() -> list[str]:
    """Load every valid package and its graph model.  Returns their ids."""
    started = time.perf_counter()
    loaded = []
    for info in list_packages():
        if not info.valid:
            continue
        try:
            get_package(info.id).graph_dataset()
            loaded.append(info.id)
        except PackageError:
            continue
    logger.info("warmup.packages ids=%s ms=%d", ",".join(loaded), (time.perf_counter() - started) * 1000)
    return loaded


async def warm_database(dataset_ids: list[str]) -> None:
    """Open a pooled connection and read each dataset's catalog.  Never raises."""
    from sqlalchemy import text

    from src.db.engine import get_engine
    from src.intelligence.catalog_access import build_catalog_source

    started = time.perf_counter()
    try:
        async with asyncio.timeout(DATABASE_WARMUP_TIMEOUT_S):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            catalog = build_catalog_source()
            for dataset_id in dataset_ids:
                package = get_package(dataset_id)
                await catalog.get_snapshot(DatasetContext(id=package.id, schema_name=package.schema_name, package=package))
    except Exception as exc:  # noqa: BLE001 - warming up is optional
        logger.info("warmup.database skipped (%s)", type(exc).__name__)
        return
    logger.info("warmup.database ms=%d", (time.perf_counter() - started) * 1000)
