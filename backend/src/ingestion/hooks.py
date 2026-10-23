"""Hooks: code that runs around the schema swap of an ingestion.

Two phases:

``pre_swap``
    runs against the new generation *before* it goes live (for example building
    the catalog from the staged data).  ``ctx.schema`` is the staging schema.
``post_swap``
    runs after the new generation is live (for example refreshing embeddings).
    ``ctx.schema`` is the live schema.

A hook never blocks a load: derived artifacts (catalog, knowledge) can be
rebuilt later, the data cannot be half-loaded.  A hook that raises or reports
``failed`` is recorded in the run report and makes the run
``succeeded_with_warnings``.

Hooks are named in the ``POST_INGEST_HOOKS`` setting as ``package.module:attr``
and imported lazily.  A module that is not installed is skipped with a warning,
so independent features can be merged in any order.

``attr`` can be

* an object with ``name``, ``phase`` and ``async run(ctx)`` (the :class:`Hook`
  protocol), or a class that builds one without arguments;
* an ``async def`` function decorated with :func:`hook`.

A hook's ``run`` returns a :class:`HookResult`, any object with ``name``,
``status`` (``ok``, ``warning`` or ``failed``), ``message`` and ``details``
attributes (it is read by duck typing), or ``None`` for "ok".
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import structlog
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from src.config import Settings, get_settings
from src.datasets.models import DatasetPackage

logger = structlog.get_logger(__name__)

Phase = Literal["pre_swap", "post_swap"]
PHASES: tuple[Phase, ...] = ("pre_swap", "post_swap")
HookStatus = Literal["ok", "warning", "failed", "skipped"]


@dataclass
class HookContext:
    """Everything a hook may use.  Valid only while the hook runs.

    ``engine`` and ``sync_engine`` connect as the owner role.  ``engine`` is an
    ``AsyncEngine`` created for this run (do not keep it); ``sync_engine`` is
    the process-wide synchronous engine.
    """

    dataset_id: str
    run_id: str
    package: DatasetPackage
    schema: str
    engine: AsyncEngine
    settings: Settings
    sync_engine: Engine | None = None
    phase: Phase = "post_swap"
    # Free-form switches from the caller, for example ``{"force": True}``.
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    name: str = ""
    phase: str = ""
    status: HookStatus = "ok"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }


@runtime_checkable
class Hook(Protocol):
    name: str
    phase: Phase

    async def run(self, ctx: HookContext) -> HookResult | None: ...


class _FunctionHook:
    def __init__(self, func: Callable[[HookContext], Awaitable[HookResult | None]], name: str, phase: Phase):
        self._func = func
        self.name = name
        self.phase = phase

    async def run(self, ctx: HookContext) -> HookResult | None:
        return await self._func(ctx)


def hook(*, phase: Phase, name: str | None = None):
    """Decorator turning ``async def f(ctx)`` into a hook."""

    def wrap(func: Callable[[HookContext], Awaitable[HookResult | None]]) -> _FunctionHook:
        return _FunctionHook(func, name or func.__name__, phase)

    return wrap


@dataclass
class LoadedHooks:
    hooks: list[Hook] = field(default_factory=list)
    skipped: list[HookResult] = field(default_factory=list)  # unavailable or unusable entries


def _as_hook(target: Any) -> Hook:
    if isinstance(target, type):
        target = target()
    if callable(getattr(target, "run", None)) and getattr(target, "phase", None) in PHASES:
        if not getattr(target, "name", None):
            target.name = type(target).__name__
        return target
    raise TypeError("not a hook: it needs a phase ('pre_swap' or 'post_swap') and an async run(ctx)")


def load_hooks(specs: list[str] | None = None) -> LoadedHooks:
    """Import the configured hooks.  Entries that cannot be used are reported in ``skipped``."""
    result = LoadedHooks()
    for spec in specs if specs is not None else get_settings().POST_INGEST_HOOKS:
        module_name, _, attr = spec.partition(":")
        if not module_name or not attr:
            logger.warning("ingest.hook.invalid_spec", spec=spec)
            result.skipped.append(HookResult(spec, "", "skipped", "Not of the form module:attr."))
            continue
        try:
            target = getattr(importlib.import_module(module_name), attr)
            result.hooks.append(_as_hook(target))
        except ModuleNotFoundError as exc:
            # Only "this hook's own module is not there" is an expected, quiet skip.
            if exc.name and (module_name == exc.name or module_name.startswith(exc.name + ".")):
                logger.warning("ingest.hook.unavailable", hook=spec)
                result.skipped.append(HookResult(spec, "", "skipped", "The hook module is not available."))
            else:
                logger.warning("ingest.hook.import_failed", hook=spec, error=type(exc).__name__)
                result.skipped.append(
                    HookResult(spec, "", "warning", "The hook could not be imported (a dependency is missing).")
                )
        except (AttributeError, TypeError) as exc:
            logger.warning("ingest.hook.unusable", hook=spec, error=type(exc).__name__)
            result.skipped.append(HookResult(spec, "", "warning", "The hook is not usable."))
        except Exception as exc:
            logger.warning("ingest.hook.import_failed", hook=spec, error=type(exc).__name__)
            result.skipped.append(HookResult(spec, "", "warning", "The hook could not be imported."))
    return result


def _coerce_result(returned: Any) -> HookResult:
    if isinstance(returned, HookResult):
        return returned
    if returned is None:
        return HookResult()
    status = str(getattr(returned, "status", "ok"))
    details = getattr(returned, "details", None)
    return HookResult(
        name=str(getattr(returned, "name", "") or ""),
        status=status if status in ("ok", "warning", "failed", "skipped") else "warning",  # type: ignore[arg-type]
        message=str(getattr(returned, "message", "") or ""),
        details=dict(details) if isinstance(details, dict) else {},
    )


async def run_hooks(hooks: list[Hook], phase: Phase, ctx: HookContext) -> list[HookResult]:
    """Run the hooks of ``phase`` in order and collect their results.

    A hook that raises is turned into a ``failed`` result (its message is generic:
    details go to the log).
    """
    ctx.phase = phase
    results: list[HookResult] = []
    for item in hooks:
        if item.phase != phase:
            continue
        started = time.monotonic()
        try:
            returned = await item.run(ctx)
            result = _coerce_result(returned)
        except Exception as exc:
            logger.error("ingest.hook.failed", hook=item.name, phase=phase, exc_info=True)
            result = HookResult(status="failed", message=f"The hook failed ({type(exc).__name__}).")
        result.name = result.name or item.name
        result.phase = phase
        result.duration_ms = int((time.monotonic() - started) * 1000)
        results.append(result)
    return results
