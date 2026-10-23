"""``graphsense ingest <dataset>``: load a dataset from its source files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from src.ingestion.report import IngestError
from src.ingestion.runner import IngestOptions, IngestOutcome, ingest
from src.storage.engines import dispose_sync_engines


def _print(outcome: IngestOutcome, verbose: bool) -> None:
    head = f"{outcome.kind} {outcome.dataset_id}: {outcome.status}"
    if outcome.dry_run:
        head += " (dry run, nothing was swapped in)"
    click.echo(head)
    if outcome.report.get("skipped_reason") == "unchanged":
        click.echo("  The source files and the package are unchanged since the live load. Use --force to load again.")
    tables = outcome.report.get("tables", {})
    if tables:
        click.echo(f"  {'table':<42}{'records':>9}{'loaded':>9}{'rejected':>10}{'duplicates':>12}")
        for name, t in tables.items():
            click.echo(f"  {name:<42}{t['records']:>9}{t['loaded']:>9}{t['rejected']:>10}{t['duplicates']:>12}")
        total = sum(t["loaded"] for t in tables.values())
        click.echo(f"  {'total':<42}{sum(t['records'] for t in tables.values()):>9}{total:>9}")
    timings = outcome.report.get("timings_ms", {})
    if timings:
        click.echo("  timings: " + ", ".join(f"{k} {v / 1000:.1f}s" for k, v in timings.items()))
    for hook in outcome.report.get("hooks", []):
        click.echo(f"  hook {hook['name'] or '?'} [{hook.get('phase') or '-'}]: {hook['status']} {hook.get('message', '')}".rstrip())
    shown = [i for i in outcome.issues if i.severity in ("error", "warning") or verbose]
    for issue in shown[: (None if verbose else 12)]:
        click.echo(f"  {issue.severity:<7} {issue.table_name}: {issue.message} (x{issue.count})")
    if len(shown) > 12 and not verbose:
        click.echo(f"  ... {len(shown) - 12} more finding(s); use -v to list them, or see the run record")
    if outcome.status == "failed":
        click.echo(f"  error [{outcome.error_code}]: {outcome.error_message}", err=True)
    click.echo(f"  run id: {outcome.run_id}")


@click.command(name="ingest", help="Load a dataset from its source files into a new generation and swap it in.")
@click.argument("dataset_id")
@click.option(
    "--data-root", type=click.Path(file_okay=False, exists=True, path_type=Path), default=None,
    help="Directory holding the source data (default: DATA_ROOT). The package names a subdirectory of it.",
)
@click.option("--force", is_flag=True, help="Load even if nothing changed since the live load.")
@click.option("--dry-run", is_flag=True, help="Load and validate in a scratch schema, record nothing, swap nothing.")
@click.option("--skip-hooks", is_flag=True, help="Do not run the configured pre/post-swap hooks.")
@click.option("--max-reject-rate", type=click.FloatRange(0, 1), default=None,
              help="Override the package's allowed share of rejected records (0-1).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable result.")
@click.option("-v", "--verbose", is_flag=True, help="List every finding.")
def command(
    dataset_id: str,
    data_root: Path | None,
    force: bool,
    dry_run: bool,
    skip_hooks: bool,
    max_reject_rate: float | None,
    as_json: bool,
    verbose: bool,
) -> None:
    options = IngestOptions(
        data_root=data_root, force=force, dry_run=dry_run, skip_hooks=skip_hooks,
        max_reject_rate=max_reject_rate, triggered_by="cli",
    )
    try:
        outcome = ingest(dataset_id, options)
    except IngestError as exc:
        raise click.ClickException(f"[{exc.code}] {exc.message}") from None
    finally:
        dispose_sync_engines()

    if as_json:
        click.echo(json.dumps(
            {
                "run_id": outcome.run_id, "dataset_id": outcome.dataset_id, "status": outcome.status,
                "table_counts": outcome.table_counts, "reject_counts": outcome.reject_counts,
                "error_code": outcome.error_code, "error_message": outcome.error_message,
                "report": outcome.report,
            },
            indent=2, default=str,
        ))
    else:
        _print(outcome, verbose)
    if outcome.status == "failed":
        sys.exit(1)
