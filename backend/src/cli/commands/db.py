"""``graphsense db ...``: the application schema and database roles."""

from __future__ import annotations

import asyncio

import click

from src.config import dsn_host, get_settings
from src.datasets.errors import PackageError
from src.datasets.registry import available_ids, get_package
from src.db.migration_runner import apply_pending, get_status
from src.storage.engines import (
    dispose_sync_engines,
    get_owner_sync_engine,
    make_owner_async_engine,
)
from src.storage.roles import APP_ROLE, READONLY_ROLE, provision_roles


def _fail(exc: Exception) -> click.ClickException:
    # Operator tool: the exception type and message are useful and carry no credentials.
    return click.ClickException(f"{type(exc).__name__}: {exc}")


@click.group(name="db", help="Migrate the application schema and set up database roles.")
def command() -> None:
    pass


@command.command("migrate", help="Apply pending migrations (as the owner role).")
def migrate() -> None:
    async def go() -> tuple[list, list[str]]:
        engine = make_owner_async_engine()
        skipped: list[str] = []
        try:
            return await apply_pending(engine, skipped), skipped
        finally:
            await engine.dispose()

    click.echo(f"Database: {dsn_host(get_settings().require_owner_dsn())}")
    try:
        applied, skipped = asyncio.run(go())
    except Exception as exc:
        raise _fail(exc) from None
    if applied:
        click.echo(f"Applied {len(applied)} migration(s): " + ", ".join(f"{m.version}__{m.name}" for m in applied))
    else:
        click.echo("No pending migrations.")
    if skipped:
        click.echo(f"Left pending (extension not available on this server): {', '.join(skipped)}", err=True)


@command.command("status", help="Show which migrations are applied.")
def status() -> None:
    async def go():
        engine = make_owner_async_engine()
        try:
            return await get_status(engine)
        finally:
            await engine.dispose()

    try:
        rows = asyncio.run(go())
    except Exception as exc:
        raise _fail(exc) from None
    for row in rows:
        click.echo(f"{row.version}  {row.status:<18} {row.name}")


@command.command(
    "provision-roles",
    help=f"Create the {APP_ROLE} and {READONLY_ROLE} roles and grant them access. Safe to repeat.",
)
@click.option("--app-password", envvar="GRAPHSENSE_APP_PASSWORD", default=None, help=f"Password for {APP_ROLE}.")
@click.option(
    "--readonly-password", envvar="GRAPHSENSE_READONLY_PASSWORD", default=None, help=f"Password for {READONLY_ROLE}."
)
def provision(app_password: str | None, readonly_password: str | None) -> None:
    settings = get_settings()
    legacy: list[str] = []
    for dataset_id in available_ids():
        try:
            legacy += [t.table for t in get_package(dataset_id).tables]
        except PackageError:
            continue
    try:
        report = provision_roles(
            get_owner_sync_engine(),
            app_password=app_password,
            readonly_password=readonly_password,
            statement_timeout_ms=settings.SQL_STATEMENT_TIMEOUT_MS,
            legacy_tables=tuple(sorted(set(legacy))),
        )
    except Exception as exc:
        raise _fail(exc) from None
    finally:
        dispose_sync_engines()
    click.echo("Roles ready: " + f"{APP_ROLE}, {READONLY_ROLE}")
    if report.created:
        click.echo("Created: " + ", ".join(report.created))
    for note in report.notes:
        click.echo(f"note: {note}")
