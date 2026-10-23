"""Keeping sensitive column values out of the catalog's consumers.

A column declared ``sensitive: true`` in a dataset package must never have
example values stored in the catalog, returned by the catalog API, or sent to a
language model.  The builder does not collect such values in the first place;
the functions here are the second line of defence, applied on every read:

* :func:`strip_sensitive_values` - what the catalog API returns;
* :func:`redact_for_llm` - what the AI layer may put in a prompt or embed.

Both are pure and return a new snapshot.  They look at the *current* package's
``sensitive`` flags (carried by the snapshot), so marking a column sensitive
takes effect immediately, even for a catalog built before the change.
"""

from __future__ import annotations

from dataclasses import replace

from src.catalog.model import CatalogSnapshot, ColumnInfo


def sensitive_columns(snapshot: CatalogSnapshot) -> frozenset[tuple[str, str]]:
    """``(table, column)`` pairs flagged sensitive."""
    return frozenset((t.name, c.name) for t in snapshot.tables for c in t.columns if c.sensitive)


def _strip_values(col: ColumnInfo) -> ColumnInfo:
    return replace(col, min_value=None, max_value=None, top_values=(), sample_values=())


def _strip_for_llm(col: ColumnInfo) -> ColumnInfo:
    return replace(_strip_values(col), value_set=None, value_labels={}, label_confidence=None)


def _map_sensitive(snapshot: CatalogSnapshot, fn) -> CatalogSnapshot:
    tables = tuple(
        replace(t, columns=tuple(fn(c) if c.sensitive else c for c in t.columns)) for t in snapshot.tables
    )
    return replace(snapshot, tables=tables)


def strip_sensitive_values(snapshot: CatalogSnapshot) -> CatalogSnapshot:
    """Remove min, max, top values and samples of sensitive columns."""
    return _map_sensitive(snapshot, _strip_values)


def redact_for_llm(snapshot: CatalogSnapshot) -> CatalogSnapshot:
    """The view of ``snapshot`` that may be shown to a language model or embedded.

    For every sensitive column: no min, max, top values, samples, or value labels.
    Names, types, roles and descriptions stay (the model needs to know the
    column exists to write SQL); aggregate statistics (null rate, distinct
    count) stay.
    """
    return _map_sensitive(snapshot, _strip_for_llm)
