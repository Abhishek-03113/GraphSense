"""``graphsense dataset ...``: inspect, roll back and drop datasets."""

from __future__ import annotations

import json

import click
from sqlalchemy import text

from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.models import DatasetPackage
from src.datasets.registry import get_package, list_packages
from src.storage import schema_manager as sm
from src.storage.engines import dispose_sync_engines, get_owner_sync_engine


def _package(dataset_id: str) -> DatasetPackage:
    try:
        return get_package(dataset_id)
    except UnknownDatasetError as exc:
        raise click.ClickException(str(exc)) from None
    except PackageError:
        raise click.ClickException("The dataset package is not valid. Run `graphsense package lint`.") from None


def _rows(sql: str, **params):
    with get_owner_sync_engine().connect() as conn:
        if not sm.has_app_schema(conn):
            return []
        return conn.execute(text(sql), params).all()


@click.group(name="dataset", help="List, inspect, roll back and drop datasets.")
def command() -> None:
    pass


@command.command("list", help="Datasets with their load status.")
def list_() -> None:
    try:
        rows = {r.id: r for r in _rows("SELECT id, status, package_version, updated_at FROM app.datasets")}
        for info in list_packages():
            row = rows.get(info.id)
            status = row.status if row else "not loaded"
            version = f"package {info.version}" if info.valid else f"INVALID: {info.error}"
            click.echo(f"{info.id:<24} {status:<12} {version}")
    finally:
        dispose_sync_engines()


@command.command("status", help="Details of one dataset and its recent runs.")
@click.argument("dataset_id")
@click.option("--json", "as_json", is_flag=True)
def status(dataset_id: str, as_json: bool) -> None:
    pkg = _package(dataset_id)
    try:
        row = next(iter(_rows("SELECT * FROM app.datasets WHERE id = :i", i=dataset_id)), None)
        runs = _rows(
            "SELECT id, kind, status, phase, started_at, finished_at, error_code FROM app.ingestion_runs "
            "WHERE dataset_id = :i ORDER BY started_at DESC LIMIT 5", i=dataset_id,
        )
        gens = sm.generations(dataset_id)
    finally:
        dispose_sync_engines()
    data = {
        "dataset": dataset_id,
        "package_version": pkg.version,
        "status": row.status if row else "not loaded",
        "generations": gens,
        "active_run_id": str(row.active_run_id) if row and row.active_run_id else None,
        "runs": [
            {"id": str(r.id), "kind": r.kind, "status": r.status, "phase": r.phase,
             "started_at": r.started_at.isoformat() if r.started_at else None,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None, "error_code": r.error_code}
            for r in runs
        ],
    }
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"{dataset_id}: {data['status']} (package {pkg.version})")
    click.echo(f"  generations: live={gens['live']} previous={gens['previous']}")
    for r in data["runs"]:
        click.echo(f"  run {r['id']}  {r['kind']:<8} {r['status']:<24} {r['started_at'] or ''}")


@command.command("rollback", help="Make the previous generation live again (run twice to roll forward).")
@click.argument("dataset_id")
def rollback(dataset_id: str) -> None:
    _package(dataset_id)
    engine = get_owner_sync_engine()
    lock = sm.DatasetLock(engine, dataset_id)
    try:
        if not lock.acquire():
            raise click.ClickException("Another operation is running on this dataset.")
        try:
            sm.rollback(dataset_id, engine=engine)
        finally:
            lock.release()
    except sm.SchemaError as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        dispose_sync_engines()
    click.echo(f"{dataset_id}: rolled back to the previous generation")


@command.command("drop", help="Delete every generation of a dataset's data (run history is kept).")
@click.argument("dataset_id")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def drop(dataset_id: str, yes: bool) -> None:
    _package(dataset_id)
    if not yes:
        click.confirm(f"Delete all data of dataset {dataset_id!r}?", abort=True)
    try:
        dropped = sm.drop_dataset(dataset_id)
    finally:
        dispose_sync_engines()
    click.echo(f"{dataset_id}: dropped {', '.join(dropped) or 'nothing (no data)'}")
