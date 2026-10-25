"""``graphsense eval <dataset>``: measure how well the Ask layer answers a dataset's golden questions.

Offline (the default) needs no model key and runs in CI; ``--live`` asks the configured model.
The report is printed, optionally written as JSON and Markdown, and stored in ``app.eval_runs``.
Exit status: 0 when the run passes, 1 when the score is under ``--fail-under`` or a golden
question is retrievable, 2 when it cannot run (unknown dataset, no key for ``--live``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from src.config import get_settings
from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import get_package
from src.db.engine import dispose_engine, get_engine
from src.intelligence.catalog_access import build_catalog_source
from src.intelligence.eval.graph_ids import DbGraphIds
from src.intelligence.eval.models import EvalReport, Mode
from src.intelligence.eval.replay import GoldenReplayLLM
from src.intelligence.eval.report import (
    diff_metrics,
    load_metrics,
    render_diff,
    render_text,
    store_report,
    write_json,
    write_markdown,
)
from src.intelligence.eval.runner import EvalOptions, Evaluator
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers.base import is_configured
from src.intelligence.providers.factory import build_providers
from src.intelligence.providers.fake import FakeEmbedder
from src.intelligence.providers.null import NullEmbedder
from src.intelligence.retrieval.hybrid import HybridRetriever
from src.intelligence.sql.executor import ReadOnlyExecutor


def _context(dataset: str) -> DatasetContext:
    try:
        package = get_package(dataset)
    except UnknownDatasetError as exc:
        raise click.UsageError(str(exc)) from None
    return DatasetContext(id=package.id, schema_name=package.schema_name, package=package)


@click.command(
    name="eval",
    help="Evaluate a dataset's golden questions and guardrail cases (offline by default, no key needed).",
)
@click.argument("dataset")
@click.option("--offline", "mode", flag_value="offline", default=True, help="Replay the reference queries; no key, no network (default).")
@click.option("--live", "mode", flag_value="live", help="Ask the configured model (needs an LLM API key, e.g. OPENROUTER_API_KEY).")
@click.option("--fail-under", type=click.FloatRange(0.0, 1.0), default=None, help="Exit 1 when the score (lowest gated metric) is below this.")
@click.option("--json", "json_path", type=click.Path(path_type=Path, dir_okay=False), default=None, help="Write the full report as JSON.")
@click.option("--markdown", "markdown_path", type=click.Path(path_type=Path, dir_okay=False), default=None, help="Write a Markdown summary.")
@click.option("--no-store", is_flag=True, help="Do not record the run in app.eval_runs.")
@click.option("--compare", "compare_to", default=None, metavar="RUN_ID", help="Show the change against an earlier stored run ('latest' for the newest).")
@click.option("--only", multiple=True, metavar="ID", help="Run only this golden question (repeatable).")
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Run at most this many golden questions.")
@click.option("--pause", type=click.FloatRange(min=0), default=0.0, help="Seconds to wait between live questions.")
def command(
    dataset: str,
    mode: str,
    fail_under: float | None,
    json_path: Path | None,
    markdown_path: Path | None,
    no_store: bool,
    compare_to: str | None,
    only: tuple[str, ...],
    limit: int | None,
    pause: float,
) -> None:
    ctx = _context(dataset)
    run_mode: Mode = "live" if mode == "live" else "offline"
    if run_mode == "live":
        providers = build_providers(get_settings())
        if not is_configured(providers.llm):
            raise click.UsageError("--live needs a language model: set OPENROUTER_API_KEY (see backend/.env.example).")
        llm, embedder, scope_embedder = providers.llm, providers.embedder, providers.embedder
    else:
        llm, embedder, scope_embedder = GoldenReplayLLM(), FakeEmbedder(), NullEmbedder("offline evaluation: lexical scope")

    async def run() -> tuple[EvalReport, str]:
        store = KnowledgeStore(get_engine)
        executor = ReadOnlyExecutor()
        evaluator = Evaluator(
            mode=run_mode,
            llm=llm,
            embedder=embedder,
            catalog=build_catalog_source(),
            executor=executor,
            retriever=HybridRetriever(store, embedder),
            scope_embedder=scope_embedder,
            graph_ids=DbGraphIds(get_engine, ctx),
            knowledge_texts=store.texts,
        )
        message = ""
        try:
            report = await evaluator.run(ctx, EvalOptions(only=only, limit=limit, pause_s=pause))
            report.fail_under = fail_under
            report.passed = not report.leakage["leaks"] and (
                fail_under is None or (report.score is not None and report.score >= fail_under)
            )
            if not no_store:
                try:
                    report.run_id = await store_report(get_engine(), report)
                except Exception as exc:  # noqa: BLE001 - a run is still useful when it cannot be recorded
                    message = f"the run was not recorded in app.eval_runs ({type(exc).__name__}); is the database migrated?"
            if compare_to:
                previous = await load_metrics(get_engine(), compare_to, ctx.id)
                if previous is None:
                    message = (message + "; " if message else "") + f"no stored run {compare_to!r} to compare with"
                else:
                    message = (message + "\n" if message else "") + render_diff(diff_metrics(previous, report.metrics))
            return report, message
        finally:
            await executor.close()
            await dispose_engine()

    try:
        report, message = asyncio.run(run())
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(f"evaluation could not run: {type(exc).__name__}: {exc}") from None

    click.echo(render_text(report))
    if message:
        click.echo(message, err=True)
    if report.run_id:
        click.echo(f"run id: {report.run_id}")
    if json_path is not None:
        write_json(report, json_path)
        click.echo(f"report: {json_path}")
    if markdown_path is not None:
        write_markdown(report, markdown_path)
    if not report.passed:
        raise SystemExit(1)
