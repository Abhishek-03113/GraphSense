"""Hooks used by the tests.  They record what they saw in ``CALLS`` and in the database."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text

from src.ingestion.hooks import HookContext, HookResult, hook

CALLS: list[dict] = []


async def _row_counts(ctx: HookContext, schema: str) -> int:
    async with ctx.engine.connect() as conn:
        tables = [r[0] for r in await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"), {"s": schema})]
        total = 0
        for name in tables:
            total += (await conn.execute(text(f'SELECT count(*) FROM "{schema}"."{name}"'))).scalar_one()
        return total


@hook(phase="pre_swap", name="fake_pre")
async def fake_pre(ctx: HookContext) -> HookResult:
    # Runs on the staged data: the schema is the staging one and is fully loaded.
    CALLS.append({"phase": ctx.phase, "schema": ctx.schema, "run_id": ctx.run_id, "rows": await _row_counts(ctx, ctx.schema)})
    return HookResult(status="ok", message="seen", details={"rows": CALLS[-1]["rows"]})


@hook(phase="post_swap", name="fake_post")
async def fake_post(ctx: HookContext) -> HookResult:
    CALLS.append({"phase": ctx.phase, "schema": ctx.schema, "run_id": ctx.run_id, "rows": await _row_counts(ctx, ctx.schema),
                  "options": dict(ctx.options)})
    return HookResult(status="ok")


@dataclass
class OwnResult:
    """Not a HookResult: results are read by duck typing."""

    name: str = "own"
    status: str = "failed"
    message: str = "could not build"
    details: dict = field(default_factory=dict)


class FailingPre:
    name = "failing_pre"
    phase = "pre_swap"

    async def run(self, ctx: HookContext):
        return OwnResult()


class RaisingPost:
    name = "raising_post"
    phase = "post_swap"

    async def run(self, ctx: HookContext):
        raise RuntimeError("secret detail /srv/path SELECT 1")


failing_pre = FailingPre()
raising_post = RaisingPost()
