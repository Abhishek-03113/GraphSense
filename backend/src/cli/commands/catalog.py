"""``graphsense catalog ...``: build and inspect the semantic catalog of a dataset."""

from __future__ import annotations

import json
import sys

import click
from sqlalchemy import Engine, create_engine

from src.catalog import repository
from src.catalog.builder import BuildInfo
from src.catalog.refresh import profile_config, refresh_on_connection
from src.config import get_settings
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.models import DatasetPackage
from src.datasets.registry import get_package


def _package(dataset_id: str) -> DatasetPackage:
    try:
        return get_package(dataset_id)
    except (UnknownDatasetError, PackageError) as exc:
        raise click.ClickException(str(exc)) from None


def _sync_engine() -> Engine:
    """A synchronous engine on the application database (operator tool: DDL-capable DSN)."""
    dsn = get_settings().require_database_dsn()
    return create_engine(dsn.replace("+asyncpg", "+psycopg2", 1), pool_pre_ping=True)


def _summary(info: BuildInfo) -> dict:
    return {
        "dataset": info.dataset_id,
        "run_id": info.run_id,
        "schema": info.schema_name,
        "tables": info.table_count,
        "columns": info.column_count,
        "relationships": info.relationship_count,
        "duration_ms": info.duration_ms,
        "drift": [d.to_dict() for d in info.drift],
        "notes": list(info.notes),
    }


@click.group(name="catalog", help="Build and inspect the semantic catalog.")
def command() -> None:
    pass


@command.command("refresh", help="Re-profile the live data of a dataset and store the catalog (no reload).")
@click.argument("dataset_id")
@click.option("--schema", default=None, help="Schema to profile (default: the dataset's live schema).")
@click.option("--run-id", default=None, help="Store the build under this run id (default: the active run).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def refresh(dataset_id: str, schema: str | None, run_id: str | None, as_json: bool) -> None:
    pkg = _package(dataset_id)
    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            if not repository.catalog_tables_exist(conn):
                raise click.ClickException("catalog tables are missing: apply the database migrations first")
            built = refresh_on_connection(
                conn, pkg, schema=schema, run_id=run_id, cfg=profile_config(get_settings())
            )
    finally:
        engine.dispose()
    summary = _summary(built.info)
    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return
    click.echo(
        f"Catalog for {pkg.id} (run {built.info.run_id}, schema {built.info.schema_name}): "
        f"{summary['tables']} tables, {summary['columns']} columns, "
        f"{summary['relationships']} relationships in {summary['duration_ms']} ms"
    )
    for table in built.snapshot.tables:
        rows = table.row_count if table.row_count is not None else "-"
        click.echo(f"  {table.name:<45} {rows:>8} rows")
    rated = [r for r in built.snapshot.relationships if r.match_rate is not None]
    if rated:
        click.echo("Relationships (share of rows with a join key that find a match)")
        for rel in rated:
            click.echo(f"  {rel.match_rate:6.1%}  {rel.expression}")
    for issue in built.info.drift:
        click.echo(f"  drift   [{issue.severity}] {issue.message}")
    for note in built.info.notes:
        click.echo(f"  note    {note}")


@command.command("show", help="Show the stored catalog build of a dataset and any drift.")
@click.argument("dataset_id")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def show(dataset_id: str, as_json: bool) -> None:
    pkg = _package(dataset_id)
    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            run = repository.active_run_id(conn, pkg.id) or repository.latest_run_id(conn, pkg.id)
            stored = repository.load_build(conn, pkg.id, run) if run else None
    finally:
        engine.dispose()
    if stored is None:
        click.echo(f"No catalog stored for {pkg.id}. Run `graphsense catalog refresh {pkg.id}`.")
        sys.exit(1)
    summary = _summary(stored.info)
    summary["stale"] = stored.info.package_hash != pkg.content_hash
    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return
    click.echo(f"Catalog for {pkg.id}: run {summary['run_id']}, built {stored.info.built_at}")
    click.echo(f"  {summary['tables']} tables, {summary['columns']} columns, {summary['relationships']} relationships")
    if summary["stale"]:
        click.echo("  the package changed since this build: refresh the catalog")
    for issue in stored.info.drift:
        click.echo(f"  drift   [{issue.severity}] {issue.message}")
    if not stored.info.drift:
        click.echo("  no drift between the package and the database")
