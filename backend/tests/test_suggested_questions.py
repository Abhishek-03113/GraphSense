"""``GET /api/datasets/{id}/suggested-questions``: package questions, minus those without data."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from src.datasets.registry import clear_package_cache
from src.db.session import get_db_session
from src.main import app
from tests.conftest import FIXTURES


class _UndefinedTable(Exception):
    sqlstate = "42P01"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _RowsSession:
    """Answers ``SELECT EXISTS (SELECT 1 FROM <table>)`` from a table -> has-rows map."""

    def __init__(self, tables: dict[str, bool | Exception]):
        self.tables = tables
        self.asked: list[str] = []

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "set_config" in sql:
            return _Result(None)
        table = sql.rsplit("FROM", 1)[1].strip(" )")
        self.asked.append(table)
        outcome = self.tables.get(table, True)
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)

    def begin_nested(self):
        class _Savepoint:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        return _Savepoint()


@pytest.fixture(autouse=True)
def _toy_packages(monkeypatch):
    monkeypatch.setenv("PACKAGES_DIR", str(FIXTURES / "packages"))
    clear_package_cache()
    yield
    clear_package_cache()


@pytest.fixture
def ask_questions():
    def call(dataset: str, tables: dict | None = None):
        session = _RowsSession(tables or {})

        async def fake_session():
            yield session

        app.dependency_overrides[get_db_session] = fake_session
        res = TestClient(app).get(f"/api/datasets/{dataset}/suggested-questions")
        return res, session

    try:
        yield call
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_every_question_is_offered_when_all_tables_have_rows(ask_questions):
    res, session = ask_questions("toy_library")
    assert res.status_code == 200
    body = res.json()
    assert body["dataset_id"] == "toy_library"
    assert [q["text"] for q in body["questions"]] == [
        "Which books are borrowed most often?",
        "How many loans are overdue?",
        "Which authors have the most books?",
    ]
    assert body["questions"][0]["category"] == "popularity"
    # one existence check per required record type, not per question
    assert len(session.asked) == len(set(session.asked)) == 3


def test_questions_whose_tables_are_empty_are_dropped(ask_questions):
    res, _ = ask_questions("toy_library", {"loans": False})
    assert [q["text"] for q in res.json()["questions"]] == ["Which authors have the most books?"]


def test_a_dataset_without_loaded_tables_offers_no_data_questions(ask_questions):
    missing = ProgrammingError("SELECT", {}, _UndefinedTable("relation does not exist"))
    res, _ = ask_questions("toy_library", {"books": missing, "loans": missing, "authors": missing})
    assert res.status_code == 200 and res.json()["questions"] == []


def test_a_failing_check_does_not_hide_questions(ask_questions):
    res, _ = ask_questions("toy_library", {"loans": RuntimeError("connection lost")})
    assert len(res.json()["questions"]) == 3
    assert "connection lost" not in res.text


def test_unknown_dataset_is_404(ask_questions):
    res, _ = ask_questions("nope")
    assert res.status_code == 404 and res.json()["code"] == "not_found"
