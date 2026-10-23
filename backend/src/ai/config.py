"""Compatibility shim: AI settings now live in :mod:`src.config`.

The legacy pipeline in ``src/ai`` reads ``GEMINI_API_KEY`` as a plain string.
This shim unwraps the secret for it and is removed together with ``src/ai``.
"""

from __future__ import annotations

from typing import Any

from src.config import get_settings


class _AISettingsShim:
    # Tests and callers may assign values; they win over the real settings.
    _overrides: dict[str, Any]

    def __init__(self) -> None:
        object.__setattr__(self, "_overrides", {})

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        settings = get_settings()
        if name == "GEMINI_API_KEY":
            return settings.GEMINI_API_KEY.get_secret_value()
        if name == "GEMINI_EMBEDDING_MODEL":
            return settings.EMBEDDING_MODEL
        return getattr(settings, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Assigning the real value again (e.g. a test restoring what it patched)
        # removes the override instead of freezing it.
        self._overrides.pop(name, None)
        if value != getattr(self, name, None):
            self._overrides[name] = value

    def __delattr__(self, name: str) -> None:
        self._overrides.pop(name, None)


ai_settings = _AISettingsShim()
