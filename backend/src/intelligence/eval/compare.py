"""Compare two query results the way a person would: by what they contain.

Execution accuracy asks "does the generated query return the same answer as the reference
query?", not "is the SQL text the same".  Two results are equal when

* they hold the same rows, in any order (a result without ORDER BY has no order, and a model
  may order differently from the reference);
* numbers agree within a small tolerance (a SUM of numerics and the same SUM as a float differ in
  the last digits) and whole numbers equal their decimal form (``3`` and ``3.00``);
* dates and timestamps agree when they name the same moment (a timestamp at midnight equals
  the date), and text agrees after trimming whitespace;
* the *columns* hold the same values, whatever they are called and in whatever order: an alias
  is a presentation choice, so columns are matched by content, not by name.

Nothing here touches a database or a dataset; the inputs are plain rows.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

REL_TOL = 1e-6
ABS_TOL = 1e-6

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
# A cell is sorted by (type rank, value); None sorts first and values of different types never mix.
_RANK = {"null": 0, "bool": 1, "num": 2, "str": 3}

Cell = tuple[str, Any]


def normalise_cell(value: Any) -> Cell:
    """A comparable form of one database or JSON value: ``(kind, value)``."""
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int | float | Decimal):
        number = float(value)
        if math.isnan(number):
            return ("str", "nan")
        return ("num", number)
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.UTC).replace(tzinfo=None)
        if value.time() == dt.time(0):
            return ("str", value.date().isoformat())
        return ("str", value.isoformat(timespec="seconds"))
    if isinstance(value, dt.date):
        return ("str", value.isoformat())
    if isinstance(value, dt.time):
        return ("str", value.isoformat(timespec="seconds"))
    text = str(value).strip()
    if _NUMBER.match(text):
        # "12.50" and 12.5 are the same answer.
        return ("num", float(text))
    iso = _iso_to_text(text)
    return ("str", iso if iso is not None else text)


def _iso_to_text(text: str) -> str | None:
    """Text that is an ISO timestamp, in the same form ``normalise_cell`` gives a datetime."""
    if len(text) < 10 or text[4:5] != "-" or text[7:8] != "-":
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return str(normalise_cell(parsed)[1])


def cells_equal(a: Cell, b: Cell, *, rel_tol: float = REL_TOL, abs_tol: float = ABS_TOL) -> bool:
    if a[0] != b[0]:
        return False
    if a[0] == "num":
        return math.isclose(a[1], b[1], rel_tol=rel_tol, abs_tol=abs_tol)
    return a[1] == b[1]


def _sort_key(cell: Cell) -> tuple:
    kind, value = cell
    if kind == "null":
        return (_RANK[kind], 0)
    if kind == "num":
        # Rounded so values equal within the tolerance sort together.
        return (_RANK[kind], float(f"{value:.6g}"))
    return (_RANK[kind], value)


def _row_key(row: Sequence[Cell]) -> tuple:
    return tuple(_sort_key(c) for c in row)


def normalise_rows(rows: Sequence[Sequence[Any]]) -> list[tuple[Cell, ...]]:
    return [tuple(normalise_cell(v) for v in row) for row in rows]


def _rows_equal(a: Sequence[Sequence[Cell]], b: Sequence[Sequence[Cell]], *, rel_tol: float, abs_tol: float) -> bool:
    """Same multiset of rows, comparing numbers with a tolerance."""
    if len(a) != len(b):
        return False
    ordered_a = sorted(a, key=_row_key)
    ordered_b = sorted(b, key=_row_key)
    return all(
        len(x) == len(y) and all(cells_equal(p, q, rel_tol=rel_tol, abs_tol=abs_tol) for p, q in zip(x, y, strict=True))
        for x, y in zip(ordered_a, ordered_b, strict=True)
    )


def _column(rows: Sequence[Sequence[Cell]], index: int) -> list[Cell]:
    return sorted((row[index] for row in rows), key=_sort_key)


def _columns_equal(a: list[Cell], b: list[Cell], *, rel_tol: float, abs_tol: float) -> bool:
    return len(a) == len(b) and all(cells_equal(p, q, rel_tol=rel_tol, abs_tol=abs_tol) for p, q in zip(a, b, strict=True))


@dataclass(frozen=True)
class Comparison:
    """Outcome of comparing a candidate result with a reference result."""

    equal: bool
    # Every reference column is present in the candidate (it may have extra ones).
    superset: bool
    reason: str = ""
    # For each reference column, the index of the candidate column it was matched with.
    mapping: tuple[int, ...] = ()


def compare_results(
    reference: Sequence[Sequence[Any]],
    candidate: Sequence[Sequence[Any]],
    *,
    rel_tol: float = REL_TOL,
    abs_tol: float = ABS_TOL,
) -> Comparison:
    """Compare ``candidate`` rows with ``reference`` rows (both without column names).

    ``equal`` is strict: the same rows and the same number of columns, columns matched by content.
    ``superset`` is lenient: the candidate may carry extra columns (a name next to an id), as long as
    the reference columns can all be found in it and the rows agree on them.
    """
    ref = normalise_rows(reference)
    cand = normalise_rows(candidate)
    if len(ref) != len(cand):
        return Comparison(False, False, f"row count differs ({len(cand)} instead of {len(ref)})")
    ref_width = len(ref[0]) if ref else _width(reference)
    cand_width = len(cand[0]) if cand else _width(candidate)
    if not ref:
        # Two empty results agree when they have the same number of columns (or the lenient reading).
        same = ref_width == cand_width
        return Comparison(same, cand_width >= ref_width, "" if same else "column count differs")
    if cand_width < ref_width:
        return Comparison(False, False, f"fewer columns ({cand_width} instead of {ref_width})")

    # Which candidate columns could stand for each reference column?
    ref_columns = [_column(ref, i) for i in range(ref_width)]
    cand_columns = [_column(cand, j) for j in range(cand_width)]
    options = [
        [j for j in range(cand_width) if _columns_equal(ref_columns[i], cand_columns[j], rel_tol=rel_tol, abs_tol=abs_tol)]
        for i in range(ref_width)
    ]
    if any(not o for o in options):
        missing = [i for i, o in enumerate(options) if not o]
        return Comparison(False, False, f"no matching column for reference column(s) {missing}")

    for mapping in _assignments(options):
        projected = [tuple(row[j] for j in mapping) for row in cand]
        if _rows_equal(ref, projected, rel_tol=rel_tol, abs_tol=abs_tol):
            return Comparison(cand_width == ref_width, True, "" if cand_width == ref_width else "extra columns", mapping)
    return Comparison(False, False, "rows differ")


def _width(rows: Sequence[Sequence[Any]]) -> int:
    return len(rows[0]) if rows else 0


def _assignments(options: list[list[int]], limit: int = 5000):
    """Injective choices of one candidate column per reference column (bounded)."""
    produced = 0

    def walk(i: int, used: frozenset[int], chosen: tuple[int, ...]):
        nonlocal produced
        if produced >= limit:
            return
        if i == len(options):
            produced += 1
            yield chosen
            return
        for j in options[i]:
            if j not in used:
                yield from walk(i + 1, used | {j}, (*chosen, j))

    yield from walk(0, frozenset(), ())
