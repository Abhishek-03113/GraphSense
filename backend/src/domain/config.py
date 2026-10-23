"""Compatibility shim: graph settings now live in :mod:`src.config`.

``graph_settings.GRAPH_DATASET`` is the default dataset id
(``DEFAULT_DATASET`` / the old ``GRAPH_DATASET`` variable).  New code should
use ``src.config.get_settings()``.
"""

from __future__ import annotations

from typing import Any

from src.config import get_settings


class _GraphSettingsShim:
    @property
    def GRAPH_DATASET(self) -> str:
        return get_settings().DEFAULT_DATASET

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)


graph_settings = _GraphSettingsShim()
