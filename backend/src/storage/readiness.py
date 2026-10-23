"""Telling "the dataset's tables are not there" apart from a real failure.

Graph queries are generated from the dataset definition, so an undefined table
or schema can only mean the data has not been loaded (yet): the dataset is
``empty``, still ``loading`` its first run, or its first load ``failed``.  The
API reports that as ``409 dataset_not_ready`` instead of a generic 500.
"""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError

# undefined_table, invalid_schema_name
MISSING_RELATION_STATES = frozenset({"42P01", "3F000"})

DATASET_NOT_READY_MESSAGE = "This dataset's data hasn't been loaded yet."


class DatasetNotReady(Exception):
    """Raised (or mapped from a database error) when a dataset has no loaded tables."""


def sqlstate_of(exc: BaseException) -> str | None:
    """The PostgreSQL SQLSTATE behind a driver error, looking through wrappers."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("sqlstate", "pgcode"):
            value = getattr(current, attr, None)
            if isinstance(value, str) and value:
                return value
        current = getattr(current, "orig", None) or current.__cause__ or current.__context__
    return None


def is_missing_relation(exc: BaseException) -> bool:
    """True when ``exc`` is a database error about a table or schema that does not exist."""
    if isinstance(exc, DatasetNotReady):
        return True
    return isinstance(exc, DBAPIError) and sqlstate_of(exc) in MISSING_RELATION_STATES
