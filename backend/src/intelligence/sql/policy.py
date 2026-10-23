"""Static rules for model-written SQL: which statements, functions, tables and casts are allowed.

These are data, not logic, so the lists are easy to review.  The guard fails
closed: anything not recognised as safe is refused.
"""

from __future__ import annotations

from sqlglot import exp


def _classes(*names: str) -> tuple[type, ...]:
    """Expression classes by name; names missing from the installed sqlglot are skipped."""
    return tuple(c for n in names if isinstance(c := getattr(exp, n, None), type))


# Statements and clauses that change data, schema, settings or locks, or run code.
FORBIDDEN_NODES: tuple[type, ...] = _classes(
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterColumn", "AlterRename",
    "AlterSet", "AlterIndex", "Command", "Copy", "Set", "SetItem", "Transaction", "Commit", "Rollback",
    "Lock", "TruncateTable", "Use", "Pragma", "Analyze", "Grant", "Revoke", "Kill", "Refresh",
    "Declare", "Cache", "Uncache", "LoadData", "Into", "Returning", "Attach", "Detach", "Show",
    "Describe", "Execute", "ExecuteSql", "Comment", "Summarize", "Export", "Install", "Call",
)  # fmt: skip

# Parameters would be bound by the driver; model-written SQL has no parameters.
PARAMETER_NODES: tuple[type, ...] = _classes("Placeholder", "Parameter", "SessionParameter")

# Typed sqlglot functions that expose the server, the session or the filesystem.
BLOCKED_TYPED: tuple[type, ...] = _classes(
    "CurrentUser", "SessionUser", "CurrentDatabase", "CurrentSchema", "CurrentSchemas",
    "CurrentCatalog", "CurrentRole", "ReadCSV", "ReadParquet", "ObjectIdentifier", "Sleep",
    "Uuid", "RandomBlob", "CurrentVersion", "Version", "ConnectionId", "LastInsertId",
)  # fmt: skip

# Function names (any capitalisation) that are never allowed, even if sqlglot knows them as a typed node.
BLOCKED_NAME_PREFIXES = (
    "pg_", "lo_", "dblink", "set_config", "current_setting", "txid_", "version", "inet_",
    "query_to_xml", "xpath", "ts_debug", "brin_", "gin_", "bt_", "pgstat", "pgrowlocks",
    "pg", "file_fdw", "copy", "load_", "system", "sys_", "exec", "shell",
)  # fmt: skip

# Casts to these types look names up in the system catalogs.
BLOCKED_CAST_TYPES = ("reg", "oid", "xid", "cid", "tid", "aclitem", "pg_")

# Functions an ``Anonymous`` node (a name sqlglot has no typed class for) may call.
ALLOWED_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset(
    ["abs", "age", "array_agg", "array_length", "array_to_string", "avg", "bool_and", "bool_or", "btrim", "cardinality", "cbrt", "ceil", "ceiling", "char_length", "character_length", "coalesce", "concat", "concat_ws", "corr", "count", "covar_pop", "covar_samp", "cume_dist", "date_part", "date_trunc", "degrees", "dense_rank", "div", "every", "exp", "extract", "first_value", "floor", "format", "generate_series", "greatest", "initcap", "isfinite", "jsonb_array_length", "jsonb_build_object", "jsonb_extract_path", "jsonb_extract_path_text", "jsonb_object_keys", "jsonb_typeof", "json_array_length", "json_typeof", "lag", "last_value", "lead", "least", "left", "length", "ln", "log", "log10", "lower", "lpad", "ltrim", "make_date", "make_interval", "make_timestamp", "max", "md5", "min", "mod", "mode", "nth_value", "ntile", "nullif", "octet_length", "percent_rank", "percentile_cont", "percentile_disc", "position", "power", "radians", "rank", "regexp_count", "regexp_match", "regexp_matches", "regexp_replace", "regexp_split_to_array", "regr_slope", "repeat", "replace", "reverse", "right", "round", "row_number", "rpad", "rtrim", "scale", "sign", "split_part", "sqrt", "starts_with", "stddev", "stddev_pop", "stddev_samp", "string_agg", "strpos", "substr", "substring", "sum", "timezone", "to_char", "to_date", "to_number", "to_timestamp", "translate", "trim", "trunc", "unnest", "upper", "variance", "var_pop", "var_samp", "width_bucket", "now", "current_date", "current_time", "current_timestamp", "localtime", "localtimestamp", "statement_timestamp", "isnumeric", "string_to_array", "array_position", "array_remove", "array_cat", "array_append", "array_prepend", "array_dims", "array_upper", "array_lower"]
)
