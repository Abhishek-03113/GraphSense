"""Type-driven coercion of raw source records into typed rows.

``row_coercer(table)`` returns a function that turns one decoded JSON record
into a tuple of Python values in the order of ``table.stored_columns()``,
together with the problems found.  What a value is converted to depends only
on the declared column type, never on how the value looks:

* ``""`` (and JSON ``null``) become NULL when the ingest policy says so;
* ``date`` accepts ``2025-03-31`` and ``2025-03-31T00:00:00.000Z``;
* ``time`` accepts the object ``{"hours":6,"minutes":49,"seconds":13}``,
  ``HH:MM:SS`` and ISO durations such as ``PT06H49M13S``;
* ``boolean`` accepts JSON booleans and the strings ``true``/``false``
  (any case) - but only on columns declared boolean, so a text column holding
  ``"True"`` stays text;
* ``decimal(p,s)`` is rounded half-up to ``s`` places and must fit ``p``;
* declared ``normalize`` steps run on text after conversion.

A row with any ``reject`` issue must not be loaded (the caller counts it).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from src.datasets.models import ColumnSpec, SqlType, StoredColumn, TableSpec
from src.datasets.normalizers import apply_normalizers

_INT = re.compile(r"^[+-]?\d+$")
_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")
_SAMPLE_CHARS = 60


@dataclass(frozen=True)
class RowIssue:
    """A problem found while coercing one record."""

    column: str | None
    code: str  # invalid_value | missing_required
    message: str
    sample: str | None = None
    severity: Literal["reject", "warn"] = "reject"


class _Bad(ValueError):
    """A value cannot be converted to the column type."""


# ---------------------------------------------------------------------------
# Converters: raw JSON value (never None or an empty string) -> typed value
# ---------------------------------------------------------------------------


def _to_text(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, bool | dict | list):
        raise _Bad("expected text")
    if isinstance(v, int | float):
        return str(v)
    raise _Bad("expected text")


def _to_int(limit: int) -> Callable[[Any], int]:
    def convert(v: Any) -> int:
        if isinstance(v, bool):
            raise _Bad("expected an integer")
        if isinstance(v, int):
            value = v
        elif isinstance(v, float):
            if not v.is_integer():
                raise _Bad("expected a whole number")
            value = int(v)
        elif isinstance(v, str) and _INT.match(v.strip()):
            value = int(v.strip())
        else:
            raise _Bad("expected an integer")
        if not -limit <= value < limit:
            raise _Bad("integer out of range")
        return value

    return convert


def _to_decimal(precision: int, scale: int) -> Callable[[Any], Decimal]:
    quantum = Decimal(1).scaleb(-scale)

    def convert(v: Any) -> Decimal:
        if isinstance(v, bool):
            raise _Bad("expected a number")
        if isinstance(v, float):
            text = repr(v)
        elif isinstance(v, int | str):
            text = str(v).strip()
        else:
            raise _Bad("expected a number")
        with localcontext() as ctx:
            ctx.prec = 80
            try:
                value = Decimal(text)
            except InvalidOperation:
                raise _Bad("expected a number") from None
            if not value.is_finite():
                raise _Bad("expected a finite number")
            value = value.quantize(quantum, rounding=ROUND_HALF_UP)
        if len(value.as_tuple().digits) > precision:
            raise _Bad(f"number too large for decimal({precision},{scale})")
        return value

    return convert


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    raise _Bad("expected true or false")


def _parse_datetime(text: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(text.strip())
    except ValueError:
        raise _Bad("expected an ISO date or timestamp") from None


def _to_date(v: Any) -> dt.date:
    if not isinstance(v, str):
        raise _Bad("expected an ISO date string")
    text = v.strip()
    if len(text) == 10:
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            raise _Bad("expected an ISO date") from None
    parsed = _parse_datetime(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.UTC)
    return parsed.date()


def _to_timestamp(v: Any) -> dt.datetime:
    if not isinstance(v, str):
        raise _Bad("expected an ISO timestamp string")
    text = v.strip()
    parsed = _parse_datetime(text if len(text) > 10 else f"{text}T00:00:00")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _to_time(v: Any) -> dt.time:
    try:
        if isinstance(v, Mapping):
            if not {"hours", "minutes", "seconds"} <= set(v):
                raise _Bad("time object needs hours, minutes and seconds")
            return dt.time(int(v["hours"]), int(v["minutes"]), int(v["seconds"]))
        if isinstance(v, str):
            text = v.strip()
            duration = _DURATION.match(text)
            if duration and any(duration.groups()):
                h, m, s = duration.groups()
                return dt.time(int(h or 0), int(m or 0), int(float(s or 0)))
            return dt.time.fromisoformat(text)
    except (ValueError, TypeError):
        raise _Bad("expected a valid time of day") from None
    raise _Bad("expected a time of day")


def _to_json(v: Any) -> Any:
    if isinstance(v, str | int | float | bool | dict | list):
        return v
    raise _Bad("expected a JSON value")


def converter_for(sql_type: SqlType) -> Callable[[Any], Any]:
    kind = sql_type.kind
    if kind == "text":
        return _to_text
    if kind == "integer":
        return _to_int(2**31)
    if kind == "bigint":
        return _to_int(2**63)
    if kind == "decimal":
        return _to_decimal(sql_type.precision or 0, sql_type.scale or 0)
    if kind == "boolean":
        return _to_bool
    if kind == "date":
        return _to_date
    if kind == "time":
        return _to_time
    if kind == "timestamp":
        return _to_timestamp
    return _to_json


# ---------------------------------------------------------------------------
# The coercer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    column: StoredColumn
    spec: ColumnSpec
    convert: Callable[[Any], Any]
    required: bool


def row_coercer(
    table: TableSpec, *, empty_string_is_null: bool = True
) -> Callable[[Mapping[str, Any]], tuple[tuple, list[RowIssue]]]:
    """Build the record -> row function for ``table``.

    The returned tuple follows ``table.stored_columns()``.  ``empty_string_is_null``
    is the package's ingest policy.
    """
    stored = table.stored_columns()
    plans = [
        _Plan(col, col.spec, converter_for(col.spec.sql_type), not col.nullable)
        for col in stored
        if not col.is_raw
    ]
    raw_cols = [(i, col) for i, col in enumerate(stored) if col.is_raw]
    raw_index = {col.name: i for i, col in raw_cols}

    def coerce(record: Mapping[str, Any]) -> tuple[tuple, list[RowIssue]]:
        issues: list[RowIssue] = []
        values: list[Any] = [None] * len(stored)
        raws: dict[str, str | None] = {}
        for index, plan in enumerate(plans):
            spec = plan.spec
            raw = record.get(spec.source)
            if empty_string_is_null and isinstance(raw, str) and raw == "":
                raw = None
            value: Any = None
            if raw is not None:
                try:
                    value = plan.convert(raw)
                    if spec.normalize:
                        if spec.keep_raw:
                            raws[spec.name] = value
                        value = apply_normalizers(value, spec.normalize)
                        if empty_string_is_null and value == "":
                            value = None
                except _Bad as exc:
                    sample = None if spec.sensitive else repr(raw)[:_SAMPLE_CHARS]
                    issues.append(RowIssue(spec.name, "invalid_value", f"{exc} ({spec.type})", sample))
            if value is None and plan.required and not any(i.column == spec.name for i in issues):
                issues.append(RowIssue(spec.name, "missing_required", "a value is required"))
            values[index] = value
        for name, i in raw_index.items():
            values[i] = raws.get(name[: -len("_raw")])
        return tuple(values), issues

    return coerce
