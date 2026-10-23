"""``SqlGuard``: decides whether a model-written query may run, and rewrites it for execution."""

from __future__ import annotations

from src.catalog import CatalogSnapshot
from src.intelligence.models import SqlRejected, ValidatedSql


class SqlGuard:
    def validate(
        self,
        sql: str,
        snapshot: CatalogSnapshot,
        *,
        schema_name: str | None = None,
        max_rows: int | None = None,
        extra_functions: tuple[str, ...] = (),
    ) -> ValidatedSql | SqlRejected:
        """Parse ``sql`` and return the query to run, or why it was refused (fail closed)."""
        raise NotImplementedError
