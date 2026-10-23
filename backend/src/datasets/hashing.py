"""Content hashing of dataset packages.

The hash is taken over the canonical JSON of the *validated* package, so it does
not change with comments, key order, file layout or YAML formatting - only with
what the package means.  Run records, knowledge refreshes and evaluations key
off it to know whether the package changed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(payload: Any) -> str:
    """sha256 of the canonical JSON of ``payload`` (a ``model_dump(mode="json")``)."""
    return sha256_hex(canonical_json(payload))
