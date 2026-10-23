"""``graphsense package ...``: work with dataset packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from src.config import get_settings
from src.datasets.ddl import schema_ddl
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.loader import load_package
from src.datasets.models import DatasetPackage
from src.datasets.registry import find_package_dir
from src.datasets.validate import validate_package


def _load(target: str) -> DatasetPackage:
    """``target`` is a package id or the path of a package directory."""
    path = Path(target)
    if path.exists():
        directory = path
    else:
        try:
            directory = find_package_dir(target)
        except UnknownDatasetError as exc:
            raise click.ClickException(str(exc)) from None
    try:
        return load_package(directory, lint=False)
    except PackageError as exc:
        raise click.ClickException(str(exc)) from None


def _default_data_dir(pkg: DatasetPackage) -> Path | None:
    root = get_settings().DATA_ROOT
    if root is None:
        return None
    candidate = Path(root) / pkg.source.default_subdir
    return candidate if candidate.is_dir() else None


@click.group(name="package", help="Inspect and validate dataset packages.")
def command() -> None:
    pass


@command.command("lint", help="Validate a package (id or directory) and report coverage.")
@click.argument("target")
@click.option(
    "--data-root", type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory holding the source data; enables checks that look at real values.",
)
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("-v", "--verbose", is_flag=True, help="List every warning.")
def lint(target: str, data_root: Path | None, strict: bool, as_json: bool, verbose: bool) -> None:
    pkg = _load(target)
    data_dir = (data_root / pkg.source.default_subdir) if data_root else _default_data_dir(pkg)
    report = validate_package(pkg, data_dir=data_dir if data_dir and data_dir.is_dir() else None)

    failed = bool(report.errors) or (strict and bool(report.warnings))
    if as_json:
        payload = {"package": pkg.id, "version": pkg.version, "content_hash": pkg.content_hash, **report.to_dict()}
        click.echo(json.dumps(payload, indent=2))
        sys.exit(1 if failed else 0)

    click.echo(f"Package {pkg.id} {pkg.version}  (content {pkg.content_hash[:12]})")
    for issue in report.errors:
        click.echo(f"  error   {issue}")
    limit = None if verbose else 15
    for issue in report.warnings[:limit]:
        click.echo(f"  warning {issue}")
    hidden = len(report.warnings) - (limit or len(report.warnings))
    if hidden > 0:
        click.echo(f"  ... {hidden} more warning(s); use -v to list them")
    if data_dir is None:
        click.echo("  note    no data directory given: checks on real values were skipped (see --data-root)")
    click.echo("Coverage")
    for line in report.coverage.summary_lines():
        click.echo(f"  {line}")
    click.echo(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    if failed:
        sys.exit(1)
    click.echo("OK")


@command.command("ddl", help="Print the CREATE statements generated for a package.")
@click.argument("target")
@click.option("--schema", default=None, help="Schema name (default: ds_<id>).")
def ddl(target: str, schema: str | None) -> None:
    pkg = _load(target)
    for statement in schema_ddl(pkg, schema or pkg.schema_name):
        click.echo(statement + ";\n")
