"""Pydantic models of a dataset package.

A package is a directory of YAML files (see ``src/datasets/loader.py``).  These
models describe, and strictly validate, what those files may contain.  They
carry no behaviour that depends on a particular dataset: everything a dataset
knows about itself (tables, columns, coded values, graph, example questions,
vocabulary) is data in the package.

Conventions
-----------
* ``extra="forbid"`` everywhere: an unknown or misspelt key is an error.
* Models are frozen, so a loaded package can be cached and shared safely.
* Table and column names are lowercase snake_case and are interpolated into
  SQL, so they are validated against a strict pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from src.datasets.hashing import content_hash
from src.datasets.normalizers import NORMALIZERS
from src.domain.graph_models import FlowDefinition
from src.domain.graph_schema import EdgeTypeDef, EntityRef, NodeTypeDef

if TYPE_CHECKING:
    from src.domain.graph_schema import GraphDataset

PACKAGE_FORMAT = 1

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PACKAGE_ID = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_TABLE_COLUMN = re.compile(r"^[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}$")
_TYPE = re.compile(
    r"^(?:(text|integer|bigint|boolean|date|time|timestamp|json)|decimal\((\d{1,2}),\s*(\d{1,2})\))$"
)
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_name(value: str, what: str) -> str:
    if not _NAME.match(value):
        raise ValueError(
            f"invalid {what} {value!r}: use lowercase letters, digits and underscores "
            "(at most 63 characters, not starting with a digit)"
        )
    return value


def _check_relative_path(value: str, what: str) -> str:
    if (
        not value
        or value.startswith(("/", "~"))
        or "\\" in value
        or "\x00" in value
        or any(part in ("..", "") for part in value.split("/"))
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError(f"{what} must be a relative path inside the data root, got {value!r}")
    return value


def derive_column_name(source: str) -> str:
    """snake_case column name for a raw (camelCase) field name.

    ``DateTime`` counts as one word, so ``lastChangeDateTime`` becomes
    ``last_change_datetime``.
    """
    text = source.replace("DateTime", "Datetime")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# ---------------------------------------------------------------------------
# Column types
# ---------------------------------------------------------------------------

Role = Literal[
    "id",
    "item_number",
    "reference",
    "code",
    "status",
    "amount",
    "quantity",
    "currency",
    "date",
    "datetime",
    "time",
    "flag",
    "name",
    "text",
    "measure",
]

ColumnKind = Literal["text", "integer", "bigint", "decimal", "boolean", "date", "time", "timestamp", "json"]


@dataclass(frozen=True)
class SqlType:
    """A column type of the package language and its PostgreSQL rendering."""

    kind: ColumnKind
    precision: int | None = None
    scale: int | None = None

    def __str__(self) -> str:
        if self.kind == "decimal":
            return f"decimal({self.precision},{self.scale})"
        return self.kind

    @property
    def ddl(self) -> str:
        """PostgreSQL type used in ``CREATE TABLE``.

        ``timestamp`` is an instant (``timestamptz``): source timestamps carry a
        UTC offset.
        """
        if self.kind == "decimal":
            return f"numeric({self.precision},{self.scale})"
        return {
            "text": "text",
            "integer": "integer",
            "bigint": "bigint",
            "boolean": "boolean",
            "date": "date",
            "time": "time",
            "timestamp": "timestamptz",
            "json": "jsonb",
        }[self.kind]


def parse_type(text: str) -> SqlType:
    match = _TYPE.match(text.strip())
    if not match:
        raise ValueError(
            f"unknown column type {text!r}; use text, integer, bigint, decimal(p,s), "
            "boolean, date, time, timestamp or json"
        )
    simple, precision, scale = match.groups()
    if simple:
        return SqlType(kind=simple)  # type: ignore[arg-type]
    p, s = int(precision), int(scale)
    if not (1 <= p <= 38 and 0 <= s <= p):
        raise ValueError(f"invalid decimal precision/scale in {text!r}")
    return SqlType(kind="decimal", precision=p, scale=s)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class ColumnSpec(_Model):
    """One stored column and the raw source field it is loaded from."""

    source: str = Field(min_length=1, max_length=128)
    # Defaults to the snake_case form of ``source`` when omitted in the YAML.
    name: str
    type: str = "text"
    role: Role | None = None
    description: str = ""
    # Closed registry of value normalisers, applied in order at ingestion.
    normalize: tuple[str, ...] = ()
    # Also keep the original text in a hidden ``<name>_raw`` column.
    keep_raw: bool = False
    value_set: str | None = None
    # "table.column" this column points at.
    refs: str | None = None
    # Never sampled into the catalog, never embedded, never sent to a language model.
    sensitive: bool = False
    hidden: bool = False
    required: bool = False
    # Name of the column of the same table that holds this amount's currency.
    currency_column: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_name(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("name") is None and isinstance(data.get("source"), str):
            data = {**data, "name": derive_column_name(data["source"])}
        return data

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_name(v, "column name")

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        return str(parse_type(v))

    @field_validator("normalize")
    @classmethod
    def _known_normalizers(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for name in v:
            if name not in NORMALIZERS:
                raise ValueError(f"unknown normaliser {name!r}; available: {', '.join(sorted(NORMALIZERS))}")
        return v

    @field_validator("value_set")
    @classmethod
    def _valid_value_set(cls, v: str | None) -> str | None:
        if v is not None and not _SLUG.match(v):
            raise ValueError(f"invalid value set id {v!r}")
        return v

    @field_validator("refs")
    @classmethod
    def _valid_refs(cls, v: str | None) -> str | None:
        if v is not None and not _TABLE_COLUMN.match(v):
            raise ValueError(f"refs must look like 'table.column', got {v!r}")
        return v

    @field_validator("currency_column")
    @classmethod
    def _valid_currency_column(cls, v: str | None) -> str | None:
        return v if v is None else _check_name(v, "currency column")

    @model_validator(mode="after")
    def _consistent(self) -> ColumnSpec:
        sql_type = parse_type(self.type)
        if (self.normalize or self.keep_raw) and sql_type.kind != "text":
            raise ValueError(f"column {self.name}: normalize and keep_raw apply to text columns only")
        if self.keep_raw and not self.normalize:
            raise ValueError(f"column {self.name}: keep_raw needs at least one normaliser")
        if self.currency_column and self.currency_column == self.name:
            raise ValueError(f"column {self.name}: currency_column cannot be the column itself")
        return self

    @property
    def sql_type(self) -> SqlType:
        return parse_type(self.type)


@dataclass(frozen=True)
class StoredColumn:
    """A column as it exists in the database (a spec column or its ``_raw`` twin)."""

    name: str
    sql_type: SqlType
    nullable: bool
    source: str
    spec: ColumnSpec
    is_raw: bool = False


class TableSource(_Model):
    # Directory (relative to the dataset's data directory) holding ``*.jsonl`` files.
    path: str

    @field_validator("path")
    @classmethod
    def _relative(cls, v: str) -> str:
        return _check_relative_path(v, "source path")


class TableSpec(_Model):
    table: str
    description: str = ""
    # What one row represents, e.g. "(order, order_line)".
    grain: str | None = None
    source: TableSource
    primary_key: tuple[str, ...]
    # Extra (non-unique) indexes, each a list of columns.  Indexes on edge columns
    # of the graph are added automatically.
    indexes: tuple[tuple[str, ...], ...] = ()
    columns: tuple[ColumnSpec, ...]
    # Raw source fields that are intentionally not stored (for example fields that
    # are empty in every record), so a new unknown field is distinguishable from these.
    ignore: tuple[str, ...] = ()
    # The load fails if fewer rows than this were stored.
    min_rows: int | None = Field(default=None, ge=0)

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check_name(v, "table name")

    @field_validator("primary_key")
    @classmethod
    def _valid_pk(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("primary_key must name at least one column")
        for col in v:
            _check_name(col, "primary key column")
        if len(set(v)) != len(v):
            raise ValueError("primary_key repeats a column")
        return v

    @field_validator("indexes")
    @classmethod
    def _valid_indexes(cls, v: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        for index in v:
            if not index:
                raise ValueError("an index needs at least one column")
            for col in index:
                _check_name(col, "index column")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> TableSpec:
        names = [c.name for c in self.columns]
        if not names:
            raise ValueError(f"table {self.table}: needs at least one column")
        if len(set(names)) != len(names):
            dup = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"table {self.table}: duplicate column name(s) {dup}")
        sources = [c.source for c in self.columns]
        if len(set(sources)) != len(sources):
            dup = sorted({n for n in sources if sources.count(n) > 1})
            raise ValueError(f"table {self.table}: source field(s) {dup} mapped to more than one column")
        taken = set(names)
        for c in self.columns:
            if c.keep_raw:
                raw = f"{c.name}_raw"
                if raw in taken:
                    raise ValueError(f"table {self.table}: column {raw} clashes with keep_raw of {c.name}")
                taken.add(raw)
        known = set(names)
        for col in self.primary_key:
            if col not in known:
                raise ValueError(f"table {self.table}: primary key column {col!r} is not a column")
        for index in self.indexes:
            for col in index:
                if col not in known:
                    raise ValueError(f"table {self.table}: index column {col!r} is not a column")
        for c in self.columns:
            if c.currency_column and c.currency_column not in known:
                raise ValueError(
                    f"table {self.table}: currency_column {c.currency_column!r} of {c.name} is not a column"
                )
        clash = sorted(set(self.ignore) & set(sources))
        if clash:
            raise ValueError(f"table {self.table}: ignored field(s) {clash} are also mapped to columns")
        if len(set(self.ignore)) != len(self.ignore):
            raise ValueError(f"table {self.table}: ignore repeats a field")
        return self

    # --- lookups ----------------------------------------------------------

    def column(self, name: str) -> ColumnSpec:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"table {self.table} has no column {name!r}")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def source_fields(self) -> frozenset[str]:
        """Raw fields the table knows about (stored or deliberately ignored)."""
        return frozenset([c.source for c in self.columns] + list(self.ignore))

    def stored_columns(self) -> tuple[StoredColumn, ...]:
        """Database columns in order: the spec columns, then any ``_raw`` twins."""
        pk = set(self.primary_key)
        out = [
            StoredColumn(
                name=c.name,
                sql_type=c.sql_type,
                nullable=not (c.required or c.name in pk),
                source=c.source,
                spec=c,
            )
            for c in self.columns
        ]
        out += [
            StoredColumn(
                name=f"{c.name}_raw",
                sql_type=SqlType(kind="text"),
                nullable=True,
                source=c.source,
                spec=c,
                is_raw=True,
            )
            for c in self.columns
            if c.keep_raw
        ]
        return tuple(out)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class SourceSpec(_Model):
    kind: Literal["jsonl_dir"] = "jsonl_dir"
    # Directory under the operator-configured data root.  Never absolute.
    default_subdir: str

    @field_validator("default_subdir")
    @classmethod
    def _relative(cls, v: str) -> str:
        return _check_relative_path(v, "default_subdir")


class IngestPolicy(_Model):
    empty_string_is_null: bool = True
    unknown_fields: Literal["warn", "error"] = "warn"
    max_reject_rate: float = Field(default=0.001, ge=0.0, le=1.0)
    on_duplicate_key: Literal["last_wins", "error"] = "last_wins"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class GraphSpec(_Model):
    """Contents of ``graph.yaml``: the graph model of the dataset."""

    node_types: tuple[NodeTypeDef, ...] = ()
    edge_types: tuple[EdgeTypeDef, ...] = ()
    flows: tuple[FlowDefinition, ...] = ()
    # (column-name substring, node type key); first match wins.
    entity_column_hints: tuple[tuple[str, str], ...] = ()
    entity_refs: tuple[EntityRef, ...] = ()


# ---------------------------------------------------------------------------
# Semantics
# ---------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low"]


class ValueSet(_Model):
    """Labels for the codes of coded columns."""

    description: str = ""
    values: dict[str, str]
    applies_to: tuple[str, ...] = ()
    # How sure the author is of the labels.  Only high and medium labels are served
    # to clients; low ones are kept in the package as a marked guess.
    confidence: Confidence = "high"
    notes: str = ""

    @field_validator("values")
    @classmethod
    def _non_empty(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("a value set needs at least one value")
        return v

    @field_validator("applies_to")
    @classmethod
    def _valid_targets(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for target in v:
            if not _TABLE_COLUMN.match(target):
                raise ValueError(f"applies_to entries look like 'table.column', got {target!r}")
        return v


class GlossaryEntry(_Model):
    id: str
    title: str
    text: str
    tables: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError(f"invalid glossary id {v!r}")
        return v


Cardinality = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]


class RelationshipSpec(_Model):
    """A join between two tables that the graph edges do not already express."""

    from_table: str
    from_columns: tuple[str, ...]
    to_table: str
    to_columns: tuple[str, ...]
    cardinality: Cardinality | None = None
    description: str = ""

    @model_validator(mode="after")
    def _valid(self) -> RelationshipSpec:
        _check_name(self.from_table, "relationship table")
        _check_name(self.to_table, "relationship table")
        if not self.from_columns or len(self.from_columns) != len(self.to_columns):
            raise ValueError("from_columns and to_columns must be non-empty and the same length")
        for col in (*self.from_columns, *self.to_columns):
            _check_name(col, "relationship column")
        return self


class ExampleExpect(_Model):
    min_rows: int | None = Field(default=None, ge=0)
    max_rows: int | None = Field(default=None, ge=0)
    columns_include: tuple[str, ...] = ()


class ExampleSpec(_Model):
    """A question with a reference query.

    ``example`` entries are retrieved into prompts as few-shot guidance.
    ``golden`` entries are only used to evaluate, and are never retrieved.
    """

    id: str
    question: str
    sql: str
    role: Literal["example", "golden"] = "example"
    tags: tuple[str, ...] = ()
    expect: ExampleExpect | None = None
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError(f"invalid example id {v!r}")
        return v


class GuardrailCase(_Model):
    question: str
    expect: Literal["allow", "reject"]


DEFAULT_OUT_OF_SCOPE = "I can answer questions about {scope_summary}. Try one of the suggested questions."


class Vocabulary(_Model):
    """What the dataset is about, used to decide whether a question is in scope."""

    scope_summary: str = ""
    terms: tuple[str, ...] = ()
    synonyms: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    # Minimum retrieval similarity for a question without a vocabulary hit to count as in scope.
    min_similarity: float = Field(default=0.40, ge=0.0, le=1.0)
    out_of_scope_message: str = DEFAULT_OUT_OF_SCOPE
    guardrail_cases: tuple[GuardrailCase, ...] = ()

    def render_out_of_scope(self) -> str:
        """The refusal text with ``{scope_summary}`` filled in."""
        return self.out_of_scope_message.replace("{scope_summary}", self.scope_summary)


class SuggestedQuestion(_Model):
    text: str
    category: str | None = None
    # Hidden when any of these node types has no rows.
    requires: tuple[str, ...] = ()


class Semantics(_Model):
    """Contents of ``semantics/*.yaml``."""

    value_sets: dict[str, ValueSet] = Field(default_factory=dict)
    glossary: tuple[GlossaryEntry, ...] = ()
    relationships: tuple[RelationshipSpec, ...] = ()
    hints: tuple[str, ...] = ()
    examples: tuple[ExampleSpec, ...] = ()
    vocabulary: Vocabulary = Field(default_factory=Vocabulary)
    suggested_questions: tuple[SuggestedQuestion, ...] = ()


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


class DatasetPackage(_Model):
    """A fully loaded and structurally validated dataset package."""

    package_format: int = PACKAGE_FORMAT
    id: str
    version: str
    name: str
    description: str = ""
    locale: str = "en"
    source: SourceSpec
    ingest: IngestPolicy = Field(default_factory=IngestPolicy)
    includes: tuple[str, ...] = ("tables/*.yaml", "graph.yaml", "semantics/*.yaml")

    tables: tuple[TableSpec, ...] = ()
    graph: GraphSpec = Field(default_factory=GraphSpec)
    semantics: Semantics = Field(default_factory=Semantics)

    _content_hash: str = PrivateAttr(default="")
    _graph_dataset: object = PrivateAttr(default=None)
    _path: Path | None = PrivateAttr(default=None)

    @field_validator("package_format")
    @classmethod
    def _supported_format(cls, v: int) -> int:
        if v != PACKAGE_FORMAT:
            raise ValueError(f"unsupported package_format {v}; this version reads {PACKAGE_FORMAT}")
        return v

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _PACKAGE_ID.match(v):
            raise ValueError(f"invalid package id {v!r}: use ^[a-z][a-z0-9_]*$ (at most 31 characters)")
        return v

    @field_validator("version")
    @classmethod
    def _valid_version(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError(f"version must be semantic (1.2.3), got {v!r}")
        return v

    @field_validator("includes")
    @classmethod
    def _valid_includes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in v:
            _check_relative_path(pattern.replace("*", "x"), "include pattern")
        return v

    @model_validator(mode="after")
    def _unique_tables(self) -> DatasetPackage:
        names = [t.table for t in self.tables]
        if len(set(names)) != len(names):
            dup = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate table(s) {dup}")
        return self

    def model_post_init(self, _context: object, /) -> None:
        self._content_hash = content_hash(self.model_dump(mode="json"))

    # --- identity ---------------------------------------------------------

    @property
    def content_hash(self) -> str:
        """sha256 of the canonical JSON of the validated package (stable across file layout)."""
        return self._content_hash

    @property
    def schema_name(self) -> str:
        """Name of the PostgreSQL schema the live dataset is stored in."""
        return f"ds_{self.id}"

    @property
    def path(self) -> Path | None:
        """Directory the package was loaded from (None for packages built in memory)."""
        return self._path

    # --- lookups ----------------------------------------------------------

    def table(self, name: str) -> TableSpec:
        for t in self.tables:
            if t.table == name:
                return t
        raise KeyError(f"package {self.id} has no table {name!r}")

    def has_table(self, name: str) -> bool:
        return any(t.table == name for t in self.tables)

    @property
    def vocabulary(self) -> Vocabulary:
        return self.semantics.vocabulary

    def value_set_of(self, table: str, column: str) -> tuple[str, ValueSet] | None:
        """The value set applying to ``table.column``: declared on the column or listing it in ``applies_to``."""
        target = f"{table}.{column}"
        declared = None
        if self.has_table(table):
            try:
                declared = self.table(table).column(column).value_set
            except KeyError:
                declared = None
        if declared and declared in self.semantics.value_sets:
            return declared, self.semantics.value_sets[declared]
        for set_id, vs in self.semantics.value_sets.items():
            if target in vs.applies_to:
                return set_id, vs
        return None

    def value_labels(self, min_confidence: Confidence = "medium") -> dict[str, dict[str, dict[str, str]]]:
        """``table -> column -> code -> label`` for every labelled column of at least ``min_confidence``."""
        out: dict[str, dict[str, dict[str, str]]] = {}
        floor = _CONFIDENCE_RANK[min_confidence]
        for table in self.tables:
            for col in table.columns:
                found = self.value_set_of(table.table, col.name)
                if found and _CONFIDENCE_RANK[found[1].confidence] >= floor:
                    out.setdefault(table.table, {})[col.name] = dict(found[1].values)
        return out

    # --- derived artifacts -------------------------------------------------

    def graph_dataset(self) -> GraphDataset:
        """The graph model as the existing ``GraphDataset`` (built once per package)."""
        if self._graph_dataset is None:
            from src.datasets.graph_adapter import build_graph_dataset

            self._graph_dataset = build_graph_dataset(self)
        return self._graph_dataset  # type: ignore[return-value]
