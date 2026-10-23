"""Value normalisers a dataset package may apply to a text column.

The registry is closed: a package names normalisers, it cannot supply code.
Each normaliser maps a string to a string and is idempotent, so applying it to
already-canonical data changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_SPACES = re.compile(r"\s+")


def strip_leading_zeros(value: str) -> str:
    """``'000010'`` becomes ``'10'``; an all-zero value becomes ``'0'``.

    Used for item numbers, which some source tables zero-pad and others do
    not, so that every table agrees on one canonical form.
    """
    stripped = value.lstrip("0")
    if stripped:
        return stripped
    return "0" if value else value


def trim(value: str) -> str:
    return value.strip()


def upper(value: str) -> str:
    return value.upper()


def lower(value: str) -> str:
    return value.lower()


def collapse_whitespace(value: str) -> str:
    """Trim and replace every run of whitespace by one space."""
    return _SPACES.sub(" ", value).strip()


NORMALIZERS: dict[str, Callable[[str], str]] = {
    "strip_leading_zeros": strip_leading_zeros,
    "trim": trim,
    "upper": upper,
    "lower": lower,
    "collapse_whitespace": collapse_whitespace,
}

# Plain-language description of each normaliser, rendered into the catalog.
NORMALIZER_DESCRIPTIONS: dict[str, str] = {
    "strip_leading_zeros": "stored without leading zeros",
    "trim": "stored without surrounding whitespace",
    "upper": "stored in upper case",
    "lower": "stored in lower case",
    "collapse_whitespace": "stored with single spaces between words",
}


def apply_normalizers(value: str, names: tuple[str, ...]) -> str:
    for name in names:
        value = NORMALIZERS[name](value)
    return value
