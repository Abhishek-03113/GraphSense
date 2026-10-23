"""The ingestion hook that builds the catalog before a freshly loaded dataset goes live.

Registered by dotted path ``src.catalog.hooks:refresh_catalog`` in
``POST_INGEST_HOOKS``.  It runs in the ``pre_swap`` phase, against the staging
schema, so the catalog describes exactly the data that is about to be
published and both switch over together.

The hook follows the ingestion engine's protocol (``src.ingestion.hooks``): ``name``,
``phase`` and ``async run(ctx)`` returning a ``HookResult``.
"""

from __future__ import annotations

from typing import Literal

from src.catalog.refresh import profile_config, refresh_on_connection, run_on
from src.ingestion.hooks import HookContext, HookResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RefreshCatalogHook:
    name = "catalog"
    phase: Literal["pre_swap", "post_swap"] = "pre_swap"

    async def run(self, ctx: HookContext) -> HookResult:
        pkg = ctx.package
        run_id = str(ctx.run_id)
        cfg = profile_config(ctx.settings)
        try:
            built = await run_on(
                ctx.engine,
                lambda conn: refresh_on_connection(
                    conn, pkg, schema=ctx.schema, run_id=run_id, cfg=cfg, commit=False
                ),
            )
        except Exception as exc:  # a catalog failure must not discard loaded data
            logger.exception("catalog build failed for %s run %s", ctx.dataset_id, run_id)
            return HookResult(
                name=self.name,
                status="failed",
                message=f"catalog build failed ({type(exc).__name__})",
                details={"error": type(exc).__name__},
            )
        info = built.info
        details = {
            "tables": info.table_count,
            "columns": info.column_count,
            "relationships": info.relationship_count,
            "duration_ms": info.duration_ms,
            "drift": len(info.drift),
            "drift_errors": sum(1 for i in info.drift if i.severity == "error"),
            "notes": list(info.notes),
        }
        problems = details["drift"] + len(info.notes)
        message = f"catalog built: {info.table_count} tables, {info.column_count} columns in {info.duration_ms} ms"
        if problems:
            message += f"; {details['drift']} drift issue(s), {len(info.notes)} note(s)"
        return HookResult(
            name=self.name, status="warning" if problems else "ok", message=message, details=details
        )


# The object the hook registry imports.
refresh_catalog = RefreshCatalogHook()
