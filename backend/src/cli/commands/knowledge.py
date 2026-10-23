"""``graphsense knowledge ...``: the Ask layer's knowledge store and query log."""

from __future__ import annotations

import asyncio
import json

import click

from src.config import get_settings
from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import get_package
from src.intelligence.catalog_access import build_catalog_source
from src.intelligence.knowledge.hooks import knowledge_engine
from src.intelligence.knowledge.refresh import knowledge_status, refresh_knowledge
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers.factory import build_providers
from src.intelligence.querylog import QueryLog


def _context(dataset: str) -> DatasetContext:
    try:
        package = get_package(dataset)
    except UnknownDatasetError as exc:
        raise click.ClickException(str(exc)) from None
    return DatasetContext(id=package.id, schema_name=package.schema_name, package=package)


@click.group(name="knowledge", help="Manage what the Ask layer retrieves from, and its query log.")
def command() -> None:
    pass


@command.command("refresh", help="Rebuild the knowledge items of a dataset (only changed items are embedded).")
@click.argument("dataset")
@click.option("--force", is_flag=True, help="Re-embed every item, even when unchanged.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def refresh(dataset: str, force: bool, as_json: bool) -> None:
    ctx = _context(dataset)
    providers = build_providers()

    async def run():
        snapshot = await build_catalog_source().get_snapshot(ctx)
        async with knowledge_engine() as engine:
            return await refresh_knowledge(KnowledgeStore(engine), snapshot, providers.embedder, force=force)

    report = asyncio.run(run())
    if as_json:
        click.echo(json.dumps(report.as_dict(), indent=2))
        return
    click.echo(
        f"{report.dataset_id}: {report.items} items, {report.inserted} added, {report.deleted} removed, "
        f"{report.embedded} embedded ({report.embed_model or 'no embedding model'}), state {report.state}"
    )
    for warning in report.warnings:
        click.echo(f"warning: {warning}", err=True)


@command.command("status", help="Show the state of a dataset's knowledge items.")
@click.argument("dataset")
def status(dataset: str) -> None:
    ctx = _context(dataset)
    providers = build_providers()

    async def run():
        snapshot = await build_catalog_source().get_snapshot(ctx)
        async with knowledge_engine() as engine:
            return await knowledge_status(KnowledgeStore(engine), ctx.id, providers.embedder, snapshot)

    st = asyncio.run(run())
    click.echo(f"{ctx.id}: {st.state}, {st.items} items, {st.embedded} embedded, mode {providers.mode}")


@command.command("purge-log", help="Delete query log entries older than the retention period.")
@click.option(
    "--older-than-days",
    type=click.IntRange(min=0),
    default=None,
    help="Override QUERY_LOG_RETENTION_DAYS (0 deletes everything).",
)
def purge_log(older_than_days: int | None) -> None:
    days = older_than_days if older_than_days is not None else get_settings().QUERY_LOG_RETENTION_DAYS

    async def run():
        async with knowledge_engine() as engine:
            return await QueryLog(engine).purge(days)

    removed = asyncio.run(run())
    click.echo(f"Deleted {removed} query log entries older than {days} days.")
