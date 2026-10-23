"""Cross-reference validation ("lint") of a dataset package.

Structural validity (types, unknown keys, identifier syntax) is checked while
the package is parsed.  This module checks what only makes sense across files:
that everything the graph, the value sets, the relationships and the example
queries mention actually exists in the tables.

``validate_package`` returns a :class:`LintReport` with

* ``errors`` - the package must not be used while any exist;
* ``warnings`` - gaps worth fixing (missing descriptions, unlabelled codes);
* ``coverage`` - counts that show how complete the semantic layer is.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import sqlglot
from pydantic import ValidationError
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify

from src.datasets.errors import LintIssue
from src.datasets.models import DatasetPackage
from src.datasets.relationships import package_relationships

# Statements that change data or the session must never appear in a reference query.
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Copy, exp.Set, exp.Transaction, exp.TruncateTable, exp.Into, exp.Lock,
)


@dataclass(frozen=True)
class Coverage:
    tables: int = 0
    columns: int = 0
    tables_with_description: int = 0
    tables_with_grain: int = 0
    columns_with_description: int = 0
    coded_columns: int = 0
    labelled_columns: int = 0
    value_sets: int = 0
    low_confidence_value_sets: int = 0
    node_types: int = 0
    edge_types: int = 0
    flows: int = 0
    glossary_entries: int = 0
    relationships: int = 0
    hints: int = 0
    examples: int = 0
    golden_examples: int = 0
    suggested_questions: int = 0
    guardrail_cases: int = 0

    def summary_lines(self) -> list[str]:
        def pct(part: int, whole: int) -> str:
            return f"{part}/{whole} ({(100 * part // whole) if whole else 0}%)"

        return [
            f"tables with description: {pct(self.tables_with_description, self.tables)}",
            f"tables with grain: {pct(self.tables_with_grain, self.tables)}",
            f"columns with description: {pct(self.columns_with_description, self.columns)}",
            f"coded columns (status/code roles) with a value set: {pct(self.labelled_columns, self.coded_columns)}",
            f"value sets: {self.value_sets} ({self.low_confidence_value_sets} low confidence)",
            f"graph: {self.node_types} node types, {self.edge_types} edge types, {self.flows} flows",
            f"relationships: {self.relationships}",
            f"glossary entries: {self.glossary_entries}, hints: {self.hints}",
            f"examples: {self.examples} few-shot, {self.golden_examples} golden",
            f"suggested questions: {self.suggested_questions}, guardrail cases: {self.guardrail_cases}",
        ]


@dataclass(frozen=True)
class LintReport:
    errors: tuple[LintIssue, ...] = ()
    warnings: tuple[LintIssue, ...] = ()
    coverage: Coverage = field(default_factory=Coverage)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
            "coverage": asdict(self.coverage),
        }


def _norm_question(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


class _Linter:
    def __init__(self, pkg: DatasetPackage):
        self.pkg = pkg
        self.errors: list[LintIssue] = []
        self.warnings: list[LintIssue] = []
        self.columns: dict[str, set[str]] = {t.table: set(t.column_names) for t in pkg.tables}

    # --- helpers ----------------------------------------------------------

    def error(self, code: str, message: str, where: str = "") -> None:
        self.errors.append(LintIssue(code, message, where))

    def warn(self, code: str, message: str, where: str = "") -> None:
        self.warnings.append(LintIssue(code, message, where))

    def check_column(self, table: str, column: str, where: str, code: str = "unknown_column") -> bool:
        if table not in self.columns:
            self.error("unknown_table", f"table {table!r} is not declared in tables/", where)
            return False
        if column not in self.columns[table]:
            self.error(code, f"column {table}.{column} does not exist", where)
            return False
        return True

    # --- checks -----------------------------------------------------------

    def tables(self) -> None:
        for t in self.pkg.tables:
            where = f"tables/{t.table}.yaml"
            if not t.description:
                self.warn("table_description", "table has no description", where)
            if not t.grain:
                self.warn("table_grain", "table has no grain (what one row represents)", where)
            pk_index = tuple(t.primary_key)
            if any(tuple(i) == pk_index for i in t.indexes):
                self.warn("redundant_index", "an index repeats the primary key", where)
            for c in t.columns:
                if not c.description:
                    self.warn("column_description", f"column {c.name} has no description", where)
                if c.role == "item_number" and "strip_leading_zeros" not in c.normalize:
                    self.warn("item_number_unnormalised", f"item number {c.name} is not normalised", where)
                if c.role == "amount" and not c.currency_column:
                    self.warn("amount_without_currency", f"amount {c.name} has no currency_column", where)
                if c.refs:
                    ref_table, ref_col = c.refs.split(".")
                    self.check_column(ref_table, ref_col, f"{where}: column {c.name} refs", "unknown_ref")
                if c.value_set and c.value_set not in self.pkg.semantics.value_sets:
                    self.error("unknown_value_set", f"column {c.name} uses undefined value set {c.value_set!r}", where)

    def graph(self) -> None:
        graph = self.pkg.graph
        if not graph.node_types:
            self.warn("no_graph", "the package defines no graph (graph.yaml has no node types)", "graph.yaml")
            return
        try:
            self.pkg.graph_dataset()
        except ValidationError as exc:
            for err in exc.errors(include_url=False, include_input=False):
                self.error("graph", err["msg"], "graph.yaml")
            return
        for n in graph.node_types:
            where = f"graph.yaml: node {n.key}"
            if n.table not in self.columns:
                self.error("unknown_table", f"table {n.table!r} is not declared", where)
                continue
            for col in (*n.id_columns, *n.detail_columns):
                self.check_column(n.table, col, where)
            if n.label_column:
                self.check_column(n.table, n.label_column, where)
            if n.label_lookup:
                lk = n.label_lookup
                for col in (lk.match_column, lk.label_column, *(c for c, _ in lk.filters)):
                    self.check_column(lk.table, col, f"{where} label_lookup")
        for e in graph.edge_types:
            where = f"graph.yaml: edge {e.key} {e.source}>{e.target}"
            for col in (*e.source_columns, *e.target_columns, *e.not_null):
                self.check_column(e.table, col, where)
        for ref in graph.entity_refs:
            self.check_column(ref.table, ref.column, f"graph.yaml: entity_ref {ref.table}.{ref.column}")

    def value_sets(self) -> None:
        owners: dict[tuple[str, str], list[str]] = {}
        for set_id, vs in self.pkg.semantics.value_sets.items():
            where = f"semantics/value_sets.yaml: {set_id}"
            if not vs.applies_to and not any(
                c.value_set == set_id for t in self.pkg.tables for c in t.columns
            ):
                self.warn("unused_value_set", "value set applies to no column", where)
            for target in vs.applies_to:
                table, column = target.split(".")
                if self.check_column(table, column, f"{where} applies_to"):
                    owners.setdefault((table, column), []).append(set_id)
            if vs.confidence == "low":
                self.warn("low_confidence_labels", "labels are a guess and are not served to clients", where)
        for t in self.pkg.tables:
            for c in t.columns:
                if c.value_set:
                    owners.setdefault((t.table, c.name), []).append(c.value_set)
        for (table, column), ids in owners.items():
            if len(set(ids)) > 1:
                self.error(
                    "value_set_conflict",
                    f"{table}.{column} is assigned to several value sets: {sorted(set(ids))}",
                    "semantics/value_sets.yaml",
                )

    def relationships(self) -> None:
        for i, rel in enumerate(self.pkg.semantics.relationships):
            where = f"semantics/relationships.yaml: #{i + 1} {rel.from_table}->{rel.to_table}"
            for col in rel.from_columns:
                self.check_column(rel.from_table, col, where)
            for col in rel.to_columns:
                self.check_column(rel.to_table, col, where)
        # Joined item numbers must be canonical in the same way on both sides.
        for join in package_relationships(self.pkg):
            if join.from_table not in self.columns or join.to_table not in self.columns:
                continue
            for a, b in zip(join.from_columns, join.to_columns, strict=True):
                if a not in self.columns[join.from_table] or b not in self.columns[join.to_table]:
                    continue
                ca = self.pkg.table(join.from_table).column(a)
                cb = self.pkg.table(join.to_table).column(b)
                if "item_number" in (ca.role, cb.role) and ca.normalize != cb.normalize:
                    self.error(
                        "normalisation_mismatch",
                        f"{join.expression}: item numbers are normalised differently "
                        f"({list(ca.normalize)} vs {list(cb.normalize)})",
                        "tables/",
                    )

    def glossary(self) -> None:
        ids = [g.id for g in self.pkg.semantics.glossary]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            self.error("duplicate_id", f"glossary id {dup!r} is used twice", "semantics/glossary.yaml")
        for g in self.pkg.semantics.glossary:
            for table in g.tables:
                if table not in self.columns:
                    self.error("unknown_table", f"glossary entry {g.id} mentions unknown table {table!r}", "semantics/glossary.yaml")

    def examples(self) -> None:
        examples = self.pkg.semantics.examples
        ids = [e.id for e in examples]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            self.error("duplicate_id", f"example id {dup!r} is used twice", "semantics/examples.yaml")
        few_shot = {_norm_question(e.question) for e in examples if e.role == "example"}
        for e in examples:
            where = f"semantics/examples.yaml: {e.id}"
            if e.role == "golden" and _norm_question(e.question) in few_shot:
                self.error("golden_leak", "a golden question repeats a few-shot example question", where)
            for problem in self.check_sql(e.sql):
                self.error("example_sql", problem, where)
            if e.expect and e.expect.columns_include:
                outputs = self.output_columns(e.sql)
                missing = [c for c in e.expect.columns_include if outputs is not None and c not in outputs]
                if missing:
                    self.error("example_expect", f"columns_include {missing} are not columns of the query", where)

    @staticmethod
    def output_columns(sql: str) -> set[str] | None:
        """Names of the result columns, or None when they cannot be known (SELECT * or parse failure)."""
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
        except SqlglotError:
            return None
        if tree is None or not isinstance(tree, exp.Select | exp.Union | exp.Subquery):
            return None
        for item in tree.expressions:
            if isinstance(item, exp.Star) or (isinstance(item, exp.Column) and isinstance(item.this, exp.Star)):
                return None
        return {name for name in tree.named_selects if name}

    def check_sql(self, sql: str) -> list[str]:
        """Problems with a reference query: parse, single SELECT, known tables and columns."""
        try:
            statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
        except SqlglotError as exc:
            return [f"does not parse: {' '.join(str(exc).split())[:160]}"]
        if len(statements) != 1:
            return [f"must be exactly one statement, found {len(statements)}"]
        tree = statements[0]
        if not isinstance(tree, exp.Select | exp.Union | exp.Subquery):
            return [f"must be a SELECT query, found {type(tree).__name__}"]
        for node in tree.walk():
            if isinstance(node, _FORBIDDEN_NODES):
                return [f"contains a forbidden construct ({type(node).__name__})"]
            if isinstance(node, exp.Select) and node.args.get("locks"):
                return ["contains FOR UPDATE / FOR SHARE"]
        problems: list[str] = []
        ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
        for table in tree.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                continue  # a table function such as generate_series(...)
            if table.db or table.catalog:
                problems.append(f"table {table.sql(dialect='postgres')} must not be schema-qualified")
            elif table.name not in self.columns and table.name not in ctes:
                problems.append(f"uses undeclared table {table.name!r}")
        if problems:
            return problems
        schema = {t: {c: "text" for c in cols} for t, cols in self.columns.items()}
        try:
            qualify(tree.copy(), schema=schema, dialect="postgres", validate_qualify_columns=True, identify=False)
        except SqlglotError as exc:
            return [f"unknown column or ambiguous reference: {' '.join(str(exc).split())[:160]}"]
        return []

    def vocabulary(self) -> None:
        vocab = self.pkg.semantics.vocabulary
        where = "semantics/vocabulary.yaml"
        if not vocab.scope_summary:
            self.warn("vocabulary_scope", "scope_summary is empty", where)
        if not vocab.terms:
            self.warn("vocabulary_terms", "no domain terms are listed", where)
        if "{scope_summary}" not in vocab.out_of_scope_message:
            self.warn("vocabulary_message", "out_of_scope_message does not mention {scope_summary}", where)
        expects = {c.expect for c in vocab.guardrail_cases}
        if "allow" not in expects or "reject" not in expects:
            self.error("guardrail_cases", "needs at least one allow and one reject guardrail case", where)
        node_keys = {n.key for n in self.pkg.graph.node_types}
        for q in self.pkg.semantics.suggested_questions:
            for key in q.requires:
                if key not in node_keys:
                    self.error("suggested_requires", f"question {q.text!r} requires unknown node type {key!r}", "semantics/suggested_questions.yaml")

    def coded_columns_from_data(self, data_dir: Path, sample_rows: int) -> None:
        """Heuristic: short text columns with few distinct values but no value set."""
        for t in self.pkg.tables:
            folder = data_dir / t.source.path
            if not folder.is_dir():
                continue
            candidates = [
                c for c in t.columns
                if c.sql_type.kind == "text" and c.role in (None, "code", "status")
                and self.pkg.value_set_of(t.table, c.name) is None
            ]
            values: dict[str, set[str]] = {c.source: set() for c in candidates}
            seen = 0
            for file in sorted(folder.glob("*.jsonl")):
                with file.open(encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        for src, bucket in values.items():
                            v = row.get(src)
                            if isinstance(v, str) and v != "":
                                bucket.add(v)
                        seen += 1
                        if seen >= sample_rows:
                            break
                if seen >= sample_rows:
                    break
            for c in candidates:
                bucket = values[c.source]
                if 1 <= len(bucket) <= 12 and all(len(v) <= 3 for v in bucket):
                    self.warn(
                        "unlabelled_code",
                        f"{t.table}.{c.name} looks like a code ({len(bucket)} distinct short values "
                        f"in the sample) but has no value set",
                        f"tables/{t.table}.yaml",
                    )

    def coverage(self) -> Coverage:
        pkg = self.pkg
        columns = [(t, c) for t in pkg.tables for c in t.columns]
        coded = [(t, c) for t, c in columns if c.role in ("code", "status")]
        sets = pkg.semantics.value_sets
        return Coverage(
            tables=len(pkg.tables),
            columns=len(columns),
            tables_with_description=sum(1 for t in pkg.tables if t.description),
            tables_with_grain=sum(1 for t in pkg.tables if t.grain),
            columns_with_description=sum(1 for _, c in columns if c.description),
            coded_columns=len(coded),
            labelled_columns=sum(1 for t, c in coded if pkg.value_set_of(t.table, c.name)),
            value_sets=len(sets),
            low_confidence_value_sets=sum(1 for v in sets.values() if v.confidence == "low"),
            node_types=len(pkg.graph.node_types),
            edge_types=len(pkg.graph.edge_types),
            flows=len(pkg.graph.flows),
            glossary_entries=len(pkg.semantics.glossary),
            relationships=len(package_relationships(pkg)),
            hints=len(pkg.semantics.hints),
            examples=sum(1 for e in pkg.semantics.examples if e.role == "example"),
            golden_examples=sum(1 for e in pkg.semantics.examples if e.role == "golden"),
            suggested_questions=len(pkg.semantics.suggested_questions),
            guardrail_cases=len(pkg.semantics.vocabulary.guardrail_cases),
        )


def validate_package(
    pkg: DatasetPackage, *, data_dir: Path | None = None, sample_rows: int = 2000
) -> LintReport:
    """Run every cross-reference check.

    ``data_dir`` (the directory the package's ``source.path`` entries are
    relative to) enables the data-based warnings.
    """
    linter = _Linter(pkg)
    linter.tables()
    linter.graph()
    linter.value_sets()
    linter.relationships()
    linter.glossary()
    linter.examples()
    linter.vocabulary()
    if data_dir is not None:
        linter.coded_columns_from_data(Path(data_dir), sample_rows)
    return LintReport(
        errors=tuple(linter.errors), warnings=tuple(linter.warnings), coverage=linter.coverage()
    )
