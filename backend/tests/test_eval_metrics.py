"""The evaluation's small measurements, each on its own."""

from dataclasses import dataclass

import pytest

from src.datasets.models import ExampleExpect
from src.intelligence.eval import metrics as m
from src.intelligence.models import EntityRef


def test_rate_ignores_unknowns_and_handles_empty():
    assert m.rate([True, False, True, None]) == pytest.approx(2 / 3)
    assert m.rate([]) is None
    assert m.rate([None]) is None
    assert m.rate([False, False]) == 0.0


def test_mean_ignores_none():
    assert m.mean([1.0, None, 3.0]) == 2.0
    assert m.mean([None]) is None


def test_percentile_nearest_rank():
    values = [10, 20, 30, 40, 50]
    assert m.percentile(values, 0.5) == 30
    assert m.percentile(values, 0.95) == 50
    assert m.percentile(values, 0.0) == 10
    assert m.percentile([7], 0.95) == 7
    assert m.percentile([], 0.5) is None
    with pytest.raises(ValueError):
        m.percentile(values, 1.5)


def test_tables_in_sql_reads_base_tables_only():
    sql = """
    WITH recent AS (SELECT * FROM loans WHERE status = 'O')
    SELECT b.title FROM recent r JOIN books b ON b.isbn = r.isbn
    WHERE b.author_id IN (SELECT author_id FROM authors)
    """
    known = {"loans", "books", "authors", "members"}
    assert m.tables_in_sql(sql, known) == {"loans", "books", "authors"}
    assert m.tables_in_sql("SELECT 1 FROM unknown_table", known) == set()
    assert m.tables_in_sql("not sql at all (", known) == set()


def test_recall():
    assert m.recall({"a", "b"}, {"a", "b", "c"}) == 1.0
    assert m.recall({"a", "b"}, {"a"}) == 0.5
    assert m.recall({"a"}, set()) == 0.0
    assert m.recall(set(), {"a"}) is None


def test_example_hit_counts_examples_sharing_a_table():
    tables = {"e1": {"books", "loans"}, "e2": {"members"}, "e3": {"authors"}}
    hit = m.example_hit({"loans"}, ["e1", "e3"], tables)
    assert (hit.relevant, hit.retrieved_relevant, hit.hit) == (1, 1, True)
    miss = m.example_hit({"members"}, ["e1"], tables)
    assert (miss.relevant, miss.hit) == (1, False)
    none = m.example_hit({"unrelated"}, ["e1"], tables)
    assert none.hit is None  # nothing could have helped


def test_expectation_problems():
    expect = ExampleExpect(min_rows=2, max_rows=3, columns_include=("Title", "isbn"))
    assert m.expectation_problems(expect, ["title", "isbn"], 2) == []
    problems = m.expectation_problems(expect, ["title"], 5)
    assert any("at most 3" in p for p in problems) and any("isbn" in p for p in problems)
    assert any("at least 2" in p for p in m.expectation_problems(expect, ["title", "isbn"], 1))
    assert m.expectation_problems(None, [], 0) == []


def entity(node_type: str, value: str) -> EntityRef:
    return EntityRef(id=f"{node_type}:{value}", type=node_type, value=value)


def test_entity_problems_structure_and_existence():
    types = {"Book", "Author"}
    good = [entity("Book", "9780000000011"), entity("Author", "A1")]
    assert m.entity_problems(good, types) == []
    assert m.entity_problems(good, types, {"Book": {"9780000000011"}, "Author": {"A1"}}) == []

    bad_type = m.entity_problems([entity("Planet", "X")], types)
    assert "unknown node type" in bad_type[0]
    assert "empty value" in m.entity_problems([entity("Book", " ")], types)[0]
    mismatched = EntityRef(id="Book:1", type="Book", value="2")
    assert "does not match" in m.entity_problems([mismatched], types)[0]
    missing = m.entity_problems([entity("Book", "nope")], types, {"Book": {"yes"}})
    assert "no such record" in missing[0]


@dataclass
class Golden:
    id: str
    question: str
    sql: str


GOLDENS = [
    Golden("g1", "How many loans are open?", "SELECT COUNT(*) FROM loans WHERE returned_at IS NULL"),
    Golden("g2", "Which members hold a gold membership?", "SELECT member_id FROM members WHERE tier = 'G'"),
]


def test_leak_by_question_ignores_case_and_punctuation():
    texts = [("item a", "Example: how MANY loans are open"), ("item b", "Some table about members")]
    report = m.find_leaks(GOLDENS, texts)
    assert report.checked == 2 and not report.clean
    assert [(x.example_id, x.what, x.source) for x in report.leaks] == [("g1", "question", "item a")]


def test_leak_by_reference_query_even_when_the_question_is_absent():
    texts = [("item", "select member_id\nfrom members where tier = 'G'")]
    report = m.find_leaks(GOLDENS, texts)
    assert [(x.example_id, x.what) for x in report.leaks] == [("g2", "sql")]


def test_clean_knowledge_has_no_leaks():
    report = m.find_leaks(GOLDENS, [("t", "Table loans: one row per loan"), ("u", "Glossary: a late loan is returned after the due date")])
    assert report.clean and report.as_dict()["leaks"] == []


def test_leak_by_id():
    leaks = m.find_id_leaks(GOLDENS, [("hit", "g2"), ("hit", "other")])
    assert [(x.example_id, x.what) for x in leaks] == [("g2", "id")]
