"""Names of the PostgreSQL schemas a dataset occupies.

For a dataset ``<id>``::

    ds_<id>              the live generation (what requests read)
    ds_<id>__r<run8>     a generation being built by a run (staging)
    ds_<id>__prev        the previous generation, kept for rollback
"""

from __future__ import annotations

import re

_DATASET_SCHEMA = re.compile(r"^ds_[a-z][a-z0-9_]*$")
_DATASET_ID = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def check_dataset_id(dataset_id: str) -> str:
    if not _DATASET_ID.match(dataset_id) or "__" in dataset_id:
        raise ValueError(f"invalid dataset id {dataset_id!r}")
    return dataset_id


def is_dataset_schema(name: str) -> bool:
    return bool(_DATASET_SCHEMA.match(name)) and len(name) <= 63


def live_schema(dataset_id: str) -> str:
    return f"ds_{check_dataset_id(dataset_id)}"


def previous_schema(dataset_id: str) -> str:
    return f"{live_schema(dataset_id)}__prev"


def staging_schema(dataset_id: str, run_id: str) -> str:
    short = re.sub(r"[^0-9a-f]", "", run_id.lower())[:8]
    if len(short) < 8:
        raise ValueError("run id too short")
    return f"{live_schema(dataset_id)}__r{short}"


def staging_prefix(dataset_id: str) -> str:
    return f"{live_schema(dataset_id)}__r"


def search_path_for(schema: str) -> str:
    """Value of ``search_path`` that reads ``schema`` and nothing else.

    No other schema is on the path, so a table missing from a dataset can never
    resolve to a table of the same name somewhere else.
    """
    if not is_dataset_schema(schema):
        raise ValueError("invalid schema name")
    return schema
