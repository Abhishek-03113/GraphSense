"""Compatibility shim: database settings now live in :mod:`src.config`.

``db_settings`` forwards attribute access to the lazily built application
settings, so importing it never requires a DSN.  New code should call
``src.config.get_settings()``; this module is removed once nothing imports it.
"""

from __future__ import annotations

from typing import Any

from src.config import get_settings


class _DatabaseSettingsShim:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        return "<db_settings shim for src.config.Settings>"


db_settings = _DatabaseSettingsShim()
