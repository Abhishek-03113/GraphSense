"""Writing an evaluation report: JSON, Markdown, a console summary, ``app.eval_runs`` and comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.intelligence.eval.models import EvalReport

# Display order and labels of the metrics (anything else follows alphabetically).
LABELS: dict[str, str] = {
    "sql_guard_acceptance": "Reference queries accepted by the SQL guard",
    "execution_success": "Questions whose query ran (read-only role)",
    "expectation_pass_rate": "Reference results meeting their expectations",
    "result_correctness": "Pipeline result equals the reference result",
    "execution_accuracy": "Execution accuracy (strict)",
    "execution_accuracy_lenient": "Execution accuracy (extra columns allowed)",
    "sql_validity": "Generated SQL accepted and run",
    "first_try_rate": "Right on the first attempt",
    "golden_scope_lexical": "Golden questions in scope by vocabulary alone",
    "golden_scope_acceptance": "Golden questions accepted by the scope check",
    "entity_validity": "Extracted entities that are graph records",
    "entity_refs_checked": "Entity references checked",
    "guardrail_pass_rate": "Guardrail cases behaving as declared",
    "guardrail_accuracy": "Guardrail accuracy",
    "retrieval_table_recall": "Retrieval recall of tables (mean)",
    "retrieval_table_full_rate": "Questions with every needed table retrieved",
    "retrieval_example_hit_rate": "Questions with a relevant example retrieved",
    "refusal_rate": "Refusals (out of scope or cannot answer)",
    "repair_rate": "Questions needing a repair attempt",
    "latency_p50_ms": "Latency, median (ms)",
    "latency_p95_ms": "Latency, p95 (ms)",
    "tokens_total": "Tokens, total",
    "tokens_per_question": "Tokens per question",
    "golden_leaks": "Golden questions found in the knowledge",
}


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}" if abs(value) < 1000 else f"{value:,.0f}"
    return str(value)


def _ordered(metrics: dict[str, Any]) -> list[str]:
    known = [k for k in LABELS if k in metrics]
    return known + sorted(k for k in metrics if k not in LABELS)


def render_text(report: EvalReport) -> str:
    lines = [
        f"Evaluation of {report.dataset_id} ({report.mode}), package {report.package_version} "
        f"[{report.package_hash[:10]}], model {report.model or 'none'}",
        f"{report.golden_count} golden questions, {report.guardrail_case_count} guardrail cases, "
        f"{report.duration_s}s, retrieval {report.retrieval_modes or 'n/a'}",
        "",
    ]
    width = max((len(LABELS.get(k, k)) for k in report.metrics), default=10)
    for key in _ordered(report.metrics):
        mark = "*" if key in report.gated else " "
        lines.append(f" {mark} {LABELS.get(key, key):<{width}}  {_fmt(report.metrics[key])}")
    lines.append("")
    lines.append(f"(* gated) score {_fmt(report.score)} = lowest gated metric" + (
        f"; fail under {report.fail_under}: {'PASS' if report.passed else 'FAIL'}" if report.fail_under is not None else ""
    ))
    if report.leakage["leaks"]:
        lines.append("")
        lines.append("GOLDEN QUESTIONS FOUND IN THE KNOWLEDGE:")
        lines += [f"  {x['example']} ({x['what']}) in {x['source']}" for x in report.leakage["leaks"]]
    failing = [c for c in report.cases if c.match is False or not c.guard_accepted or c.expectation_problems or c.entities.problems]
    if failing:
        lines.append("")
        lines.append("Questions with a problem:")
        for c in failing:
            why = c.match_reason or c.guard_message or "; ".join(c.expectation_problems + c.entities.problems)
            lines.append(f"  {c.id}: {why}")
    bad_cases = [g for g in report.guardrail_cases if not g.passed]
    if bad_cases:
        lines.append("")
        lines.append("Guardrail cases that did not behave as declared:")
        lines += [f"  expected {g.expect}, got {g.got}: {g.question}" for g in bad_cases]
    for note in report.notes:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def render_markdown(report: EvalReport) -> str:
    out = [
        f"# Evaluation: {report.dataset_id} ({report.mode})",
        "",
        f"- Package {report.package_version} (`{report.package_hash[:12]}`), prompt {report.prompt_version}, "
        f"model `{report.model or 'none'}`, embeddings `{report.embedding_model or 'none'}`",
        f"- {report.golden_count} golden questions, {report.guardrail_case_count} guardrail cases, {report.duration_s}s",
        f"- Score {_fmt(report.score)} (lowest of: {', '.join(report.gated) or 'nothing gated'})",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    out += [f"| {LABELS.get(k, k)} | {_fmt(report.metrics[k])} |" for k in _ordered(report.metrics)]
    out += ["", "## Questions", "", "| Question | Guard | Ran | Matches | Tables | Notes |", "| --- | --- | --- | --- | --- | --- |"]
    for c in report.cases:
        recall = "n/a" if c.retrieval.table_recall is None else f"{c.retrieval.table_recall:.2f}"
        notes = c.match_reason or c.guard_message or "; ".join(c.expectation_problems + c.entities.problems)
        out.append(
            f"| {c.id} | {'yes' if c.guard_accepted else 'NO'} | {'yes' if c.sql_valid else 'NO'} "
            f"| {_yn(c.match)} | {recall} | {notes} |"
        )
    out += ["", "## Guardrail cases", "", "| Question | Expected | Got |", "| --- | --- | --- |"]
    out += [f"| {g.question} | {g.expect} | {g.got}{'' if g.passed else ' (wrong)'} |" for g in report.guardrail_cases]
    if report.leakage["leaks"]:
        out += ["", "## Leaks", ""] + [f"- {x['example']} ({x['what']}) in {x['source']}" for x in report.leakage["leaks"]]
    return "\n".join(out) + "\n"


def _yn(value: bool | None) -> str:
    return "n/a" if value is None else ("yes" if value else "NO")


def write_json(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=2, default=str) + "\n", encoding="utf-8")


def write_markdown(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")


# ---------------------------------------------------------------------------
# app.eval_runs
# ---------------------------------------------------------------------------


async def store_report(engine: Any, report: EvalReport) -> str:
    """Insert the run into ``app.eval_runs`` and return its id."""
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO app.eval_runs (dataset_id, mode, package_hash, model, metrics, report) "
                "VALUES (:d, :mode, :hash, :model, CAST(:metrics AS jsonb), CAST(:report AS jsonb)) RETURNING id"
            ),
            {
                "d": report.dataset_id,
                "mode": report.mode,
                "hash": report.package_hash,
                "model": report.model or None,
                "metrics": json.dumps(report.metrics),
                "report": json.dumps(report.as_dict(), default=str),
            },
        )
        return str(row.scalar_one())


async def load_metrics(engine: Any, run_id: str, dataset_id: str | None = None) -> dict[str, Any] | None:
    """Metrics of a stored run (``run_id`` may be ``latest`` for the newest run of ``dataset_id``)."""
    if run_id == "latest":
        sql = "SELECT metrics FROM app.eval_runs WHERE dataset_id = :d ORDER BY ts DESC LIMIT 1"
        params: dict[str, Any] = {"d": dataset_id}
    else:
        sql = "SELECT metrics FROM app.eval_runs WHERE id = CAST(:i AS uuid)"
        params = {"i": run_id}
    async with engine.connect() as conn:
        value = await conn.scalar(text(sql), params)
    if value is None:
        return None
    return value if isinstance(value, dict) else json.loads(value)


def diff_metrics(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, Any, Any, float | None]]:
    """``(metric, old, new, change)`` for every metric present in both runs, in display order."""
    rows = []
    for key in _ordered(new):
        if key not in old:
            continue
        a, b = old[key], new[key]
        change = float(b) - float(a) if isinstance(a, int | float) and isinstance(b, int | float) else None
        rows.append((key, a, b, change))
    return rows


def render_diff(rows: list[tuple[str, Any, Any, float | None]]) -> str:
    lines = ["Compared with the earlier run:"]
    for key, a, b, change in rows:
        arrow = "" if change is None or abs(change) < 1e-9 else (f"  ({change:+.3f})")
        lines.append(f"  {LABELS.get(key, key)}: {_fmt(a)} -> {_fmt(b)}{arrow}")
    return "\n".join(lines)
