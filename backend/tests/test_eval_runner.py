"""The evaluation runner, driven by stubs: no database, no network."""

import json
from pathlib import Path

import pytest

from src.datasets import load_package
from src.intelligence.eval.replay import GoldenReplayLLM
from src.intelligence.eval.report import diff_metrics, render_diff, render_markdown, render_text, write_json
from src.intelligence.eval.runner import EvalOptions, Evaluator
from src.intelligence.models import ExecutionError, ExecutionResult
from src.intelligence.providers import FakeEmbedder, FakeLLM, NullEmbedder
from src.intelligence.retrieval.hybrid import HybridRetriever
from tests.ask_support import PackageCatalogSource, context, draft

GOLDEN_IDS = ["open_loans", "late_loans", "norwegian_books", "gold_members", "total_late_fees"]


class EchoExecutor:
    """Answers any query with one row shaped like its own output columns."""

    degraded = False

    def __init__(self, by_sql: dict[str, ExecutionResult] | None = None, fail_on: str | None = None) -> None:
        self.by_sql = by_sql or {}
        self.fail_on = fail_on
        self.seen: list[str] = []

    async def execute(self, schema_name, validated):
        self.seen.append(validated.sql)
        if self.fail_on and self.fail_on in validated.sql:
            raise ExecutionError("syntax", "boom")
        for fragment, result in self.by_sql.items():
            if fragment in validated.sql:
                return result
        names = tuple(p.name for p in validated.projections)
        return ExecutionResult(names, ("text",) * len(names), [tuple(f"v{i}" for i in range(len(names)))])


class FakeGraphIds:
    def __init__(self, ids: dict[str, set[str]]) -> None:
        self._ids = ids

    async def ids(self, node_types):
        return {t: self._ids.get(t, set()) for t in node_types}


def offline(package, **kwargs) -> Evaluator:
    embedder = FakeEmbedder()
    params = {
        "mode": "offline",
        "llm": GoldenReplayLLM(),
        "embedder": embedder,
        "catalog": PackageCatalogSource(),
        "executor": EchoExecutor(),
        "retriever": HybridRetriever(None, embedder),
        "scope_embedder": NullEmbedder(),
    }
    params.update(kwargs)
    return Evaluator(**params)


async def test_an_offline_run_over_the_toy_package(toy_package):
    ids = FakeGraphIds({"Loan": {"v0"}, "Member": {"v0", "v1"}, "Book": {"v0"}})
    report = await offline(toy_package, graph_ids=ids).run(context(toy_package))

    assert [c.id for c in report.cases] == GOLDEN_IDS
    m = report.metrics
    assert m["sql_guard_acceptance"] == m["execution_success"] == m["result_correctness"] == 1.0
    assert m["expectation_pass_rate"] == 1.0
    assert m["golden_scope_lexical"] == m["golden_scope_acceptance"] == 1.0
    assert m["entity_validity"] == 1.0 and m["entity_refs_checked"] == 4
    assert m["guardrail_pass_rate"] == 1.0
    assert m["retrieval_table_recall"] == 1.0
    assert m["golden_leaks"] == 0
    assert report.score == 1.0 and report.gated and "execution_accuracy" not in m
    assert report.mode == "offline" and report.model == "golden-replay" and report.read_only_role
    assert report.golden_count == 5 and report.guardrail_case_count == 9
    assert report.retrieval_modes == {"memory": 5}


async def test_the_replay_model_gives_the_reference_query_to_the_pipeline(toy_package):
    executor = EchoExecutor()
    await offline(toy_package, executor=executor).run(context(toy_package), EvalOptions(only=("gold_members",)))
    # once as the reference, once through the pipeline
    assert len([q for q in executor.seen if "members" in q.lower()]) == 2


async def test_the_report_is_json_serialisable_and_renders(toy_package, tmp_path: Path):
    report = await offline(toy_package).run(context(toy_package))
    path = tmp_path / "out" / "report.json"
    write_json(report, path)
    data = json.loads(path.read_text())
    assert data["version"] == 1 and data["dataset_id"] == "toy_library"
    assert {"metrics", "cases", "guardrail_cases", "leakage", "gated", "score"} <= set(data)
    assert data["cases"][0]["retrieval"]["tables_expected"] == ["loans"]
    text = render_text(report)
    assert "score 1.000" in text and "Evaluation of toy_library (offline)" in text
    assert "| Metric | Value |" in render_markdown(report)


async def test_a_golden_question_in_the_knowledge_fails_the_run(toy_package):
    async def stored(dataset_id):
        return [("example", "something", "Reminder: which members hold a Gold membership?")]

    report = await offline(toy_package, knowledge_texts=stored).run(context(toy_package))
    assert report.metrics["golden_leaks"] == 1
    assert report.leakage["leaks"][0]["example"] == "gold_members"
    assert "stored item example:something" in report.leakage["leaks"][0]["source"]
    assert report.score == 0.0


async def test_a_golden_id_used_as_a_stored_reference_is_a_leak(toy_package):
    async def stored(dataset_id):
        return [("example", "late_loans", "unrelated text")]

    report = await offline(toy_package, knowledge_texts=stored).run(context(toy_package))
    assert [x["what"] for x in report.leakage["leaks"]] == ["id"]


async def test_an_unreadable_store_does_not_stop_the_run(toy_package):
    async def broken(dataset_id):
        raise RuntimeError("no database")

    report = await offline(toy_package, knowledge_texts=broken).run(context(toy_package))
    assert report.leakage["stored_items"] == 0 and report.score == 1.0


async def test_entities_that_are_not_in_the_graph_lower_validity(toy_package):
    report = await offline(toy_package, graph_ids=FakeGraphIds({})).run(context(toy_package))
    assert report.metrics["entity_validity"] == 0.0
    assert report.score == 0.0
    assert any("no such record" in p for c in report.cases for p in c.entities.problems)


async def test_a_reference_query_that_fails_is_reported(toy_package):
    report = await offline(toy_package, executor=EchoExecutor(fail_on="late_fee")).run(context(toy_package))
    broken = next(c for c in report.cases if c.id == "total_late_fees")
    assert broken.guard_accepted and not broken.reference_ok and "syntax" in broken.guard_message
    assert report.metrics["execution_success"] < 1.0
    assert report.score < 1.0


async def test_a_reference_query_the_guard_refuses_is_reported(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("SELECT SUM(late_fee) AS total_late_fees FROM loans", "SELECT pg_read_file('/etc/passwd') AS total_late_fees")})
    package = load_package(path, lint=False)
    report = await offline(package).run(context(package))
    case = next(c for c in report.cases if c.id == "total_late_fees")
    assert not case.guard_accepted and case.guard_message
    assert report.metrics["sql_guard_acceptance"] == pytest.approx(4 / 5)


async def test_expectations_are_checked_against_the_reference_result(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("expect: {min_rows: 1, columns_include: [open_loans]}", "expect: {min_rows: 2, columns_include: [open_loans]}")})
    package = load_package(path, lint=False)
    report = await offline(package).run(context(package))
    case = next(c for c in report.cases if c.id == "open_loans")
    assert case.expectation_problems and "at least 2" in case.expectation_problems[0]
    assert report.metrics["expectation_pass_rate"] == pytest.approx(4 / 5)


async def test_guardrail_cases_that_misbehave_are_listed(package_copy):
    path = package_copy(edits={"semantics/vocabulary.yaml": ("{question: Write me a poem about autumn, expect: reject}", "{question: Write me a poem about autumn, expect: allow}")})
    package = load_package(path, lint=False)
    report = await offline(package).run(context(package))
    bad = [g for g in report.guardrail_cases if not g.passed]
    assert [(g.question, g.expect, g.got) for g in bad] == [("Write me a poem about autumn", "allow", "reject")]
    assert report.metrics["guardrail_pass_rate"] == pytest.approx(8 / 9, abs=1e-3)
    assert "Guardrail cases that did not behave" in render_text(report)


async def test_only_and_limit_select_questions(toy_package):
    ev = offline(toy_package)
    assert [c.id for c in (await ev.run(context(toy_package), EvalOptions(only=("gold_members",)))).cases] == ["gold_members"]
    assert len((await ev.run(context(toy_package), EvalOptions(limit=2))).cases) == 2
    report = await ev.run(context(toy_package), EvalOptions(only=("nope",)))
    assert report.cases == [] and any("unknown golden id" in n for n in report.notes)


async def test_a_dataset_that_is_not_loaded_is_called_out(toy_package):
    class NotReady:
        degraded = False

        async def execute(self, schema_name, validated):
            raise ExecutionError("unknown_table", "missing", not_ready=True)

    report = await offline(toy_package, executor=NotReady()).run(context(toy_package))
    assert any("not loaded" in n for n in report.notes)
    assert report.metrics["execution_success"] == 0.0


async def test_a_degraded_executor_is_noted(toy_package):
    executor = EchoExecutor()
    executor.degraded = True
    report = await offline(toy_package, executor=executor).run(context(toy_package))
    assert not report.read_only_role and any("READONLY_DATABASE_DSN" in n for n in report.notes)


# ---------------------------------------------------------------------------
# live mode: a model that may be wrong
# ---------------------------------------------------------------------------


def live(package, llm, executor=None, **kwargs) -> Evaluator:
    embedder = FakeEmbedder()
    return Evaluator(
        mode="live",
        llm=llm,
        embedder=embedder,
        catalog=PackageCatalogSource(),
        executor=executor or EchoExecutor(),
        retriever=HybridRetriever(None, embedder),
        **kwargs,
    )


def question_of(req) -> str:
    """The question line of a SQL-writing or repair prompt (it follows the QUESTION heading)."""
    return req.prompt.split("QUESTION\n")[-1].split("\n")[0] if "QUESTION\n" in req.prompt else ""


def is_answer_request(req) -> bool:
    return bool(req.json_schema) and "answer" in req.json_schema.get("properties", {})


def scripted(by_question: dict[str, str]) -> FakeLLM:
    """A model that answers each question with a chosen query (found by a word of the question)."""

    def script(req):
        if is_answer_request(req):
            return {"answer": "ok"}
        for needle, sql in by_question.items():
            if needle in question_of(req):
                return json.loads(draft(sql))
        return json.loads(draft(None, can_answer=False, reason="no idea"))

    return FakeLLM(script)


REFERENCE_SQL = {
    "returned late": "SELECT loan_id, member_id FROM loans WHERE status = 'L'",
    "Norwegian": "SELECT isbn, title FROM books WHERE language = 'NO'",
    "gold membership": "SELECT member_id, full_name FROM members WHERE tier = 'G'",
    "sum of all late fees": "SELECT SUM(late_fee) AS total_late_fees FROM loans",
    "loans are still open": "SELECT COUNT(*) AS open_loans FROM loans WHERE returned_at IS NULL",
}


async def test_a_model_that_writes_different_but_equivalent_sql_is_still_right(toy_package):
    # Other aliases, other column order: the answer is what counts.
    llm = scripted(
        {
            **REFERENCE_SQL,
            "gold membership": "SELECT m.full_name AS who, m.member_id AS id FROM members m WHERE m.tier = 'G'",
        }
    )
    executor = EchoExecutor({"who": ExecutionResult(("who", "id"), ("text", "text"), [("v1", "v0")])})
    report = await live(toy_package, llm, executor).run(context(toy_package))
    case = next(c for c in report.cases if c.id == "gold_members")
    assert case.match and case.generated_sql and "who" in case.generated_sql
    assert report.metrics["execution_accuracy"] == 1.0
    assert "result_correctness" not in report.metrics
    assert set(report.gated) == {"execution_accuracy", "guardrail_accuracy"}
    assert report.metrics["tokens_total"] > 0 and report.metrics["latency_p95_ms"] is not None


async def test_a_wrong_answer_lowers_execution_accuracy_not_validity(toy_package):
    llm = scripted({**REFERENCE_SQL, "Norwegian": "SELECT isbn, title FROM books WHERE language = 'EN'"})
    executor = EchoExecutor({"'EN'": ExecutionResult(("isbn", "title"), ("text", "text"), [("other", "other")])})
    report = await live(toy_package, llm, executor).run(context(toy_package))
    wrong = next(c for c in report.cases if c.id == "norwegian_books")
    assert wrong.sql_valid and wrong.match is False and "no matching column" in wrong.match_reason
    assert report.metrics["execution_accuracy"] == pytest.approx(4 / 5)
    assert report.metrics["sql_validity"] == 1.0
    assert report.score == pytest.approx(4 / 5)


async def test_a_refusal_counts_against_accuracy_and_in_the_refusal_rate(toy_package):
    llm = scripted({k: v for k, v in REFERENCE_SQL.items() if k != "gold membership"})
    report = await live(toy_package, llm).run(context(toy_package))
    refused = next(c for c in report.cases if c.id == "gold_members")
    assert refused.refused and refused.match is False and refused.error == "sql_generation_failed"
    assert report.metrics["refusal_rate"] == pytest.approx(1 / 5)


async def test_extra_columns_count_only_in_the_lenient_metric(toy_package):
    llm = scripted({**REFERENCE_SQL, "gold membership": "SELECT member_id, full_name, tier FROM members WHERE tier = 'G'"})
    executor = EchoExecutor({"tier FROM": ExecutionResult(("member_id", "full_name", "tier"), ("text",) * 3, [("v0", "v1", "G")])})
    report = await live(toy_package, llm, executor).run(context(toy_package))
    case = next(c for c in report.cases if c.id == "gold_members")
    assert case.match is False and case.match_superset is True
    assert report.metrics["execution_accuracy"] == pytest.approx(4 / 5)
    assert report.metrics["execution_accuracy_lenient"] == 1.0


async def test_a_repaired_query_is_counted(toy_package):
    state = {"first": True}

    def script(req):
        if is_answer_request(req):
            return {"answer": "ok"}
        question = question_of(req)
        if "gold membership" in question and state["first"]:
            state["first"] = False
            return json.loads(draft("SELECT member_id FROM members WHERE tier = 'G' AND nonexistent = 1"))
        for needle, sql in REFERENCE_SQL.items():
            if needle in question:
                return json.loads(draft(sql))
        return json.loads(draft(None, can_answer=False))

    report = await live(toy_package, FakeLLM(script)).run(context(toy_package))
    repaired = next(c for c in report.cases if c.id == "gold_members")
    assert repaired.attempts == 2 and not repaired.first_try_ok and repaired.sql_valid
    assert report.metrics["repair_rate"] == pytest.approx(1 / 5)
    assert report.metrics["first_try_rate"] == pytest.approx(4 / 5)


def test_metric_diff_lists_changes_in_display_order():
    rows = diff_metrics({"result_correctness": 0.8, "golden_leaks": 0, "gone": 1}, {"golden_leaks": 0, "result_correctness": 0.9, "new": 1})
    assert [(r[0], r[1], r[2]) for r in rows] == [("result_correctness", 0.8, 0.9), ("golden_leaks", 0, 0)]
    assert "+0.100" in render_diff(rows)
