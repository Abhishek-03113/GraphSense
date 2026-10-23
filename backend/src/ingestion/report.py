"""What an ingestion run reports: errors, row-level findings and per-table results.

Everything here ends up in ``app.ingestion_runs`` / ``app.ingestion_issues`` and
is returned by the admin API, so messages are written in this module's callers
in plain words and never contain driver text, SQL or filesystem paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.storage.runs import IssueRow

SAMPLE_CAP = 200  # samples kept per (table, code)
SAMPLES_PER_ISSUE = 20


class IngestError(Exception):
    """A run cannot continue.  ``code`` is a stable identifier, ``message`` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class IngestBusy(IngestError):
    """Another run holds the dataset."""

    def __init__(self) -> None:
        super().__init__("busy", "Another ingestion is already running for this dataset.")


class IssueCollector:
    """Aggregates findings by (table, severity, code, column, message) and caps the samples."""

    def __init__(self, sample_cap: int = SAMPLE_CAP):
        self.sample_cap = sample_cap
        self._issues: dict[tuple, dict[str, Any]] = {}
        self._budget: dict[tuple[str, str], int] = {}

    def add(
        self,
        table: str,
        severity: str,
        code: str,
        message: str,
        *,
        column: str | None = None,
        sample: dict[str, Any] | None = None,
        count: int = 1,
    ) -> None:
        key = (table, severity, code, column, message)
        entry = self._issues.setdefault(key, {"count": 0, "samples": []})
        entry["count"] += count
        if sample is not None and len(entry["samples"]) < SAMPLES_PER_ISSUE:
            budget_key = (table, code)
            used = self._budget.get(budget_key, 0)
            if used < self.sample_cap:
                entry["samples"].append(sample)
                self._budget[budget_key] = used + 1

    def count(self, severity: str | None = None, table: str | None = None, code: str | None = None) -> int:
        """Total occurrences matching the filters."""
        return sum(
            v["count"]
            for (t, s, c, _col, _msg), v in self._issues.items()
            if (severity is None or s == severity) and (table is None or t == table) and (code is None or c == code)
        )

    def kinds(self, severity: str) -> int:
        """Number of distinct findings of a severity."""
        return sum(1 for (_t, s, *_rest) in self._issues if s == severity)

    def rows(self) -> list[IssueRow]:
        rows = []
        for (table, severity, code, column, message), v in self._issues.items():
            sample: dict[str, Any] | None = None
            if v["samples"] or column:
                sample = {}
                if column:
                    sample["column"] = column
                if v["samples"]:
                    sample["examples"] = v["samples"]
            rows.append(IssueRow(table, severity, code, message, v["count"], sample))
        return rows

    def reject_counts(self) -> dict[str, dict[str, int]]:
        """``table -> code -> rows`` for findings that rejected rows."""
        out: dict[str, dict[str, int]] = {}
        for (table, _s, code, _col, _msg), v in self._issues.items():
            if code in REJECT_CODES:
                out.setdefault(table, {})
                out[table][code] = out[table].get(code, 0) + v["count"]
        return out


# Codes of findings that reject a row (as opposed to observations about loaded data).
REJECT_CODES = frozenset({"invalid_json", "not_an_object", "invalid_value", "missing_required", "invalid_text"})


@dataclass
class TableResult:
    table: str
    files: int = 0
    bytes: int = 0
    records: int = 0  # non-blank lines read
    rejected: int = 0
    duplicates: int = 0
    loaded: int = 0
    duration_ms: int = 0
    columns_seen: set[str] = field(default_factory=set)

    def reject_rate(self) -> float:
        return self.rejected / self.records if self.records else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "bytes": self.bytes,
            "records": self.records,
            "loaded": self.loaded,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "duration_ms": self.duration_ms,
        }
