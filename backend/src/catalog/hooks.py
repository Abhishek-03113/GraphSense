"""The ingestion hook that builds the catalog before a freshly loaded dataset goes live.

Registered by dotted path ``src.catalog.hooks:refresh_catalog`` in
``POST_INGEST_HOOKS``.  It runs in the ``pre_swap`` phase, against the staging
schema, so the catalog describes exactly the data that is about to be
published and both switch over together.

The hook follows the ingestion engine's protocol (``name``, ``phase``,
``async run(ctx)``).  The types are declared here as protocols so this module
imports without the ingestion package; whatever context object the runner
passes in works as long as it has the attributes below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from src.catalog.refresh import profile_config, refresh_on_connection, run_on
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.datasets.models import DatasetPackage

logger = get_logger(__name__)


class HookContext(Protocol):
    """The part of the ingestion runner's context this hook reads."""

    dataset_id: str
    run_id: Any
    package: DatasetPackage
    schema: str
    engine: Any
    settings: Any


@dataclass(frozen=True)
class CatalogHookResult:
    """Outcome of the hook.  ``status`` is ``ok``, ``warning`` (built, but with drift or gaps) or ``failed``."""

    name: str
    status: Literal["ok", "warning", "failed"]
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class RefreshCatalogHook:
    name = "catalog"
    phase: Literal["pre_swap", "post_swap"] = "pre_swap"

    async def run(self, ctx: HookContext) -> CatalogHookResult:
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
            return CatalogHookResult(
                self.name, "failed", f"catalog build failed ({type(exc).__name__})", {"error": type(exc).__name__}
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
        return CatalogHookResult(self.name, "warning" if problems else "ok", message, details)


# The object the hook registry imports.
refresh_catalog = RefreshCatalogHook()
