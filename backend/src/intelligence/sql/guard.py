"""``SqlGuard``: decides whether a model-written query may run, and rewrites it for execution.

The guard parses the text with sqlglot (PostgreSQL dialect) and applies, in
order:

1. exactly one statement, and it must be a query (``SELECT`` / set operation);
2. no statement or clause that writes, locks, sets options or runs code;
3. a function allowlist (a function sqlglot cannot type must be on the list);
4. a table allowlist taken from the catalog, optionally qualified with the
   dataset's own schema and nothing else;
5. a column check: the query is qualified against the catalog schema, so an
   unknown or ambiguous column is found before the database sees the query;
6. a row cap: the outer ``LIMIT`` is added or lowered to ``max_rows + 1``.

What runs is the validated tree rendered back to SQL (comments removed), and
that text is parsed and checked again, so the executed statement is itself
known to satisfy the rules.  Every doubt is a rejection (fail closed).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, TokenError
from sqlglot.optimizer.qualify import qualify

from src.catalog import CatalogSnapshot
from src.config import get_settings
from src.intelligence.models import RejectCategory, SqlRejected, ValidatedSql
from src.intelligence.sql.lineage import analyze_projections, is_aggregate_only
from src.intelligence.sql.policy import (
    ALLOWED_ANONYMOUS_FUNCTIONS,
    BLOCKED_CAST_TYPES,
    BLOCKED_NAME_PREFIXES,
    BLOCKED_TYPED,
    FORBIDDEN_NODES,
    PARAMETER_NODES,
)

# sqlglot logs a warning for every statement it cannot parse; rejections are reported by the guard.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "postgres"
MAX_SQL_CHARS = 20_000
MAX_NODES = 4_000
_SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_ .\-]")


def _clean(text: str, limit: int = 80) -> str:
    """Text taken from the model's own SQL, made safe to echo back to it and to log."""
    return _SAFE_IDENT.sub("", _ANSI.sub("", str(text)))[:limit]


def _reject(code: str, message: str, category: RejectCategory = "policy") -> SqlRejected:
    return SqlRejected(code=code, message=message, category=category)


@dataclass(frozen=True)
class _Checked:
    tables: tuple[str, ...]


class SqlGuard:
    """Stateless; one instance can serve every request."""

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
        try:
            return self._validate(sql, snapshot, schema_name, max_rows, extra_functions)
        except RecursionError:
            return _reject("too_complex", "The query is nested too deeply.")
        except Exception:
            logging.getLogger(__name__).exception("SqlGuard failed on a query")
            return _reject("validation_error", "The query could not be checked.")

    # ------------------------------------------------------------------

    def _validate(
        self,
        sql: str,
        snapshot: CatalogSnapshot,
        schema_name: str | None,
        max_rows: int | None,
        extra_functions: tuple[str, ...],
    ) -> ValidatedSql | SqlRejected:
        cap = max_rows or get_settings().SQL_MAX_ROWS
        text = (sql or "").strip()
        if not text:
            return _reject("empty", "No query was written.", "syntax")
        if len(text) > MAX_SQL_CHARS:
            return _reject("too_long", "The query is too long.")
        if "\x00" in text:
            return _reject("invalid_characters", "The query contains invalid characters.")

        parsed = self._parse(text)
        if isinstance(parsed, SqlRejected):
            return parsed
        root = parsed

        allowed_functions = ALLOWED_ANONYMOUS_FUNCTIONS | {f.lower() for f in extra_functions}
        checked = self._check_policy(root, snapshot, schema_name, allowed_functions)
        if isinstance(checked, SqlRejected):
            return checked

        # Column check and lineage run on a qualified copy; the original tree is what gets rewritten.
        qualified = self._qualify(root, snapshot)
        if isinstance(qualified, SqlRejected):
            return qualified
        projections = analyze_projections(qualified)

        user_limit, fetch_limit = self._apply_row_cap(root, cap)
        final_sql = root.sql(dialect=DIALECT, comments=False)

        # What will run must itself satisfy the rules.
        again = self._parse(final_sql)
        if isinstance(again, SqlRejected):
            return _reject("unstable_rewrite", "The query could not be rewritten safely.")
        recheck = self._check_policy(again, snapshot, schema_name, allowed_functions)
        if isinstance(recheck, SqlRejected):
            return recheck

        return ValidatedSql(
            sql=final_sql,
            original=text,
            tables=checked.tables,
            projections=projections,
            row_cap=cap,
            fetch_limit=fetch_limit,
            user_limit=user_limit,
            aggregate_only=is_aggregate_only(qualified, projections),
        )

    # --- 1. parse ---------------------------------------------------------

    @staticmethod
    def _parse(text: str) -> exp.Expression | SqlRejected:
        try:
            statements = sqlglot.parse(text, dialect=DIALECT)
        except ParseError as err:
            detail = ""
            if err.errors:
                detail = _clean(err.errors[0].get("description", ""), 120)
            return _reject("syntax_error", f"Syntax error: {detail}".strip().rstrip(":"), "syntax")
        except TokenError:
            return _reject("syntax_error", "Syntax error: the query contains text that cannot be read.", "syntax")
        statements = [s for s in statements if s is not None]
        if not statements:
            return _reject("empty", "No query was written.", "syntax")
        if len(statements) != 1:
            return _reject("multiple_statements", "Only a single SELECT statement is allowed.")
        root = statements[0]
        while isinstance(root, exp.Subquery) and not root.args.get("alias"):
            root = root.this
        if not isinstance(root, exp.Select | exp.SetOperation):
            return _reject("not_a_select", "Only SELECT queries are allowed.")
        return root

    # --- 2-4. policy ------------------------------------------------------

    def _check_policy(
        self,
        root: exp.Expression,
        snapshot: CatalogSnapshot,
        schema_name: str | None,
        allowed_functions: frozenset[str] | set[str],
    ) -> _Checked | SqlRejected:
        # One walk gathers everything the later checks need.
        nodes = list(root.walk())
        if len(nodes) > MAX_NODES:
            return _reject("too_complex", "The query is too large.")

        cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
        known = {name.lower(): name for name in snapshot.table_names}
        tables_used: list[str] = []

        for node in nodes:
            if isinstance(node, FORBIDDEN_NODES):
                return _reject("not_read_only", "Only read-only SELECT queries are allowed.")
            if isinstance(node, PARAMETER_NODES):
                return _reject("parameters", "Query parameters are not allowed.")
            if isinstance(node, BLOCKED_TYPED):
                return _reject("function_not_allowed", "That function is not allowed.")

            if isinstance(node, exp.Anonymous):
                name = str(node.name or "").lower()
                if "." in name or not name:
                    return _reject("function_not_allowed", "That function is not allowed.")
                if name not in allowed_functions or name.startswith(BLOCKED_NAME_PREFIXES):
                    return _reject("function_not_allowed", f"The function {_clean(name, 40)} is not allowed.")
            elif isinstance(node, exp.Func):
                sql_name = str(node.sql_name() or "").lower()
                if sql_name.startswith(BLOCKED_NAME_PREFIXES):
                    return _reject("function_not_allowed", "That function is not allowed.")

            if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
                return _reject("function_not_allowed", "Schema-qualified functions are not allowed.")

            if isinstance(node, exp.Cast | exp.TryCast):
                target = node.args.get("to")
                if isinstance(target, exp.DataType):
                    if target.this == exp.DataType.Type.USERDEFINED:
                        return _reject("type_not_allowed", "That cast is not allowed.")
                    kind = str(target.this.value if hasattr(target.this, "value") else target.this).lower()
                    if kind.startswith(BLOCKED_CAST_TYPES):
                        return _reject("type_not_allowed", "That cast is not allowed.")

            if isinstance(node, exp.Table):
                outcome = self._check_table(node, known, cte_names, schema_name, snapshot)
                if isinstance(outcome, SqlRejected):
                    return outcome
                if outcome:
                    tables_used.append(outcome)

        return _Checked(tables=tuple(dict.fromkeys(tables_used)))

    @staticmethod
    def _check_table(
        node: exp.Table,
        known: dict[str, str],
        cte_names: set[str],
        schema_name: str | None,
        snapshot: CatalogSnapshot,
    ) -> str | None | SqlRejected:
        """Return the catalog table a reference points at, ``None`` for CTEs and table functions."""
        this = node.this
        if not isinstance(this, exp.Identifier):
            return None  # a table function; the function check covers it
        if node.args.get("catalog"):
            return _reject("schema_not_allowed", "Cross-database references are not allowed.")
        schema = node.args.get("db")
        if schema is not None:
            wanted = schema_name or "public"
            if not isinstance(schema, exp.Identifier) or schema.name != wanted or not _SCHEMA.match(schema.name):
                return _reject("schema_not_allowed", "Only the dataset's own tables may be queried.")
        elif this.name.lower() in cte_names:
            return None
        name = this.name
        if this.args.get("quoted"):
            real = name if name in snapshot.table_names else None
        else:
            real = known.get(name.lower())
        if real is None:
            shown = ", ".join(snapshot.table_names[:40])
            return _reject(
                "unknown_table",
                f"Unknown table {_clean(name, 60)!r}. Available tables: {shown}.",
                "unknown_table",
            )
        return real

    # --- 5. columns -------------------------------------------------------

    @staticmethod
    def _qualify(root: exp.Expression, snapshot: CatalogSnapshot) -> exp.Expression | SqlRejected:
        copy = root.copy()
        for table in copy.find_all(exp.Table):
            if table.args.get("db"):
                table.set("db", None)  # already checked; the schema argument has no schema level
        try:
            return qualify(
                copy,
                schema=snapshot.sql_schema(),
                dialect=DIALECT,
                expand_stars=True,
                validate_qualify_columns=True,
                quote_identifiers=False,
            )
        except OptimizeError as err:
            return _column_error(str(err), root, snapshot)

    # --- 6. row cap -------------------------------------------------------

    @staticmethod
    def _apply_row_cap(root: exp.Expression, cap: int) -> tuple[int | None, int]:
        """Make the outer LIMIT at most ``cap + 1``.  Returns ``(limit written by the model, executed limit)``."""
        limit = root.args.get("limit")
        user_limit: int | None = None
        if isinstance(limit, exp.Limit):
            value = limit.expression
            if isinstance(value, exp.Literal) and not value.is_string and value.name.isdigit():
                user_limit = int(value.name)
        elif isinstance(limit, exp.Fetch):
            count = limit.args.get("count")
            if (
                isinstance(count, exp.Literal)
                and count.name.isdigit()
                and not limit.args.get("percent")
                and not limit.args.get("with_ties")
            ):
                user_limit = int(count.name)
        if user_limit is not None and user_limit <= cap:
            if isinstance(limit, exp.Fetch):
                root.set("limit", exp.Limit(expression=exp.Literal.number(user_limit)))
            return user_limit, user_limit
        root.set("limit", exp.Limit(expression=exp.Literal.number(cap + 1)))
        return None, cap + 1


# ---------------------------------------------------------------------------
# Messages the model can act on (built from the catalog, never from database text)
# ---------------------------------------------------------------------------

_COLUMN_NAME = re.compile(r"Column '([^']{1,80})'|Unknown column: (\S{1,80})")


def _column_error(message: str, root: exp.Expression, snapshot: CatalogSnapshot) -> SqlRejected:
    match = _COLUMN_NAME.search(message)
    column = _clean(next((g for g in (match.groups() if match else ()) if g), ""), 60)
    used: list[str] = []
    for table in root.find_all(exp.Table):
        real = table.name.lower()
        for t in snapshot.tables:
            if t.name.lower() == real and t.name not in used:
                used.append(t.name)
    listing = "; ".join(
        f"{name}({', '.join(snapshot.table(name).column_names)})" for name in used[:6]
    )
    subject = (
        f"Column {column!r} could not be resolved: it does not exist in the tables used, "
        "or it exists in several of them and needs a table alias"
        if column
        else "A column could not be resolved"
    )
    hint = f" Columns of the tables used: {listing}." if listing else "."
    return SqlRejected(code="unknown_column", message=f"{subject}.{hint}".replace("..", "."), category="unknown_column")
