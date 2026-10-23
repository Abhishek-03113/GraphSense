"""The read model of the semantic catalog.

A :class:`CatalogSnapshot` is everything the graph API and the AI layer need
to know about a dataset's data: tables, columns (with roles, descriptions,
value labels and profile statistics), relationships, glossary, example
questions and vocabulary.

These are immutable dataclasses with no behaviour that depends on a dataset.
A snapshot can be built from a package alone (``CatalogSnapshot.from_package``,
no database) or by the catalog builder from the package plus the live data
(statistics filled in); consumers use the same type either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from src.datasets.models import Vocabulary

if TYPE_CHECKING:
    from src.datasets.models import DatasetPackage


@dataclass(frozen=True)
class ValueCount:
    """A frequent value of a column, with its label when the column is coded."""

    value: str
    count: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class ColumnInfo:
    table: str
    name: str
    ordinal: int
    data_type: str
    nullable: bool = True
    role: str | None = None
    description: str = ""
    is_pk: bool = False
    sensitive: bool = False
    hidden: bool = False
    value_set: str | None = None
    # code -> label, empty for columns that are not coded.
    value_labels: dict[str, str] = field(default_factory=dict)
    label_confidence: str | None = None
    currency_column: str | None = None
    refs: str | None = None
    normalize: tuple[str, ...] = ()
    # Profile statistics; None until the catalog is built against live data.
    null_rate: float | None = None
    distinct_count: int | None = None
    min_value: str | None = None
    max_value: str | None = None
    # Never filled for sensitive columns.
    top_values: tuple[ValueCount, ...] = ()
    sample_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str = ""
    grain: str | None = None
    primary_key: tuple[str, ...] = ()
    row_count: int | None = None
    # Graph node type backed by this table, when there is one.
    node_type: str | None = None
    columns: tuple[ColumnInfo, ...] = ()

    def column(self, name: str) -> ColumnInfo:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"table {self.name} has no column {name!r}")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class RelationshipInfo:
    from_table: str
    from_columns: tuple[str, ...]
    to_table: str
    to_columns: tuple[str, ...]
    kind: Literal["graph_edge", "declared"] = "declared"
    cardinality: str | None = None
    # SQL join condition, e.g. "child.parent_id = parent.id".
    expression: str = ""
    description: str = ""
    # Share of rows of the from-table that find a match; None until measured.
    match_rate: float | None = None
    # Share of rows of the to-table that some from-table row points at; None until measured.
    coverage: float | None = None


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    title: str
    text: str
    tables: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExampleInfo:
    id: str
    question: str
    sql: str
    role: Literal["example", "golden"] = "example"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogSnapshot:
    dataset_id: str
    name: str
    description: str
    package_version: str
    package_hash: str
    tables: tuple[TableInfo, ...] = ()
    relationships: tuple[RelationshipInfo, ...] = ()
    glossary: tuple[GlossaryEntry, ...] = ()
    examples: tuple[ExampleInfo, ...] = ()
    # Dataset-specific rules to follow when writing SQL.
    hints: tuple[str, ...] = ()
    vocabulary: Vocabulary = field(default_factory=Vocabulary)
    # Run that produced the live data this snapshot describes; None for a package-only snapshot.
    run_id: str | None = None
    source: Literal["package", "live"] = "package"

    @classmethod
    def from_package(cls, pkg: DatasetPackage) -> CatalogSnapshot:
        """A snapshot built from the package alone: no database, no profile statistics."""
        from src.catalog.static import snapshot_from_package

        return snapshot_from_package(pkg)

    # --- lookups ----------------------------------------------------------

    def table(self, name: str) -> TableInfo:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"unknown table {name!r}")

    def has_table(self, name: str) -> bool:
        return any(t.name == name for t in self.tables)

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tables)

    def few_shot_examples(self) -> tuple[ExampleInfo, ...]:
        """Examples that may be shown to a model.  Golden examples are for evaluation only."""
        return tuple(e for e in self.examples if e.role == "example")

    def golden_examples(self) -> tuple[ExampleInfo, ...]:
        return tuple(e for e in self.examples if e.role == "golden")

    # --- sensitivity ------------------------------------------------------

    def llm_safe_view(self) -> CatalogSnapshot:
        """This snapshot with every value of a ``sensitive`` column removed (see ``src.catalog.safety``).

        Anything put in a prompt, embedded or sent to a model provider must come from this view.
        """
        from src.catalog.safety import redact_for_llm

        return redact_for_llm(self)

    def sensitive_columns(self) -> frozenset[tuple[str, str]]:
        """``(table, column)`` pairs flagged sensitive."""
        from src.catalog.safety import sensitive_columns

        return sensitive_columns(self)

    def sql_schema(self) -> dict[str, dict[str, str]]:
        """``{table: {column: type}}``, the shape SQL tooling (sqlglot) expects."""
        return {t.name: {c.name: c.data_type for c in t.columns} for t in self.tables}
