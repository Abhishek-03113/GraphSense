"""A second, unrelated dataset proves nothing in the engine is tied to order-to-cash.

Everything derived from the toy package (DDL, graph SQL, catalog, API payloads) is
searched for order-to-cash vocabulary, and the engine's own source is scanned for it.
"""

import dataclasses
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.catalog import CatalogSnapshot
from src.config import BACKEND_DIR, override_settings
from src.datasets import schema_ddl
from src.datasets.registry import get_package
from src.domain.graph_registry import get_dataset
from src.main import app
from src.repositories.graph_sql import GraphSqlBuilder
from tests.conftest import FIXTURES, TOY_DIR
from tests.sql_snapshot import canon, snapshot

# Words that belong to the reference dataset and must not leak into anything generic.
O2C = re.compile(
    r"o2c|\bsap\b|order[ _-]?to[ _-]?cash|sales[ _]?order|billing|invoice|delivery|deliveries|customer"
    r"|journal|payment|plant|material|business[ _]?partner",
    re.IGNORECASE,
)


def _has_o2c(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in O2C.finditer(text)})


def test_the_toy_package_loads_and_describes_a_different_domain(toy_package):
    assert [t.table for t in toy_package.tables] == ["authors", "books", "loans", "members"]
    assert toy_package.graph_dataset().node_keys == ["Author", "Book", "Member", "Loan"]


def test_toy_ddl_has_no_order_to_cash_vocabulary(toy_package):
    assert _has_o2c("\n".join(schema_ddl(toy_package, toy_package.schema_name))) == []


def test_toy_graph_sql_has_no_order_to_cash_vocabulary(toy_package):
    builder = GraphSqlBuilder(toy_package.graph_dataset())
    sql = builder.edges_union() + "".join(builder.entities_query(n) + builder.count_query(n) for n in toy_package.graph.node_types)
    assert _has_o2c(sql) == []
    assert "FROM books b" in builder.edge_select(toy_package.graph.edge_types[0])


async def test_toy_repository_statements_have_no_order_to_cash_vocabulary(toy_package):
    statements = await snapshot(toy_package.graph_dataset())
    assert _has_o2c(json.dumps(statements)) == []


async def test_toy_graph_sql_matches_its_baseline(toy_package):
    baseline = json.loads((FIXTURES / "graph_sql_baseline_toy_library.json").read_text(encoding="utf-8"))
    assert await snapshot(toy_package.graph_dataset()) == baseline


def test_toy_catalog_snapshot_has_no_order_to_cash_vocabulary(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    assert _has_o2c(json.dumps(dataclasses.asdict(snap), default=str)) == []
    assert snap.table_names == ("authors", "books", "loans", "members")
    assert [e.id for e in snap.few_shot_examples()] == ["most_borrowed_books", "books_by_author"]
    assert [e.id for e in snap.golden_examples()] == ["open_loans"]


def test_toy_codes_and_labels(toy_package):
    labels = toy_package.value_labels(min_confidence="low")
    assert labels["authors"]["home_country"]["NO"] == "Norway"  # NO survives YAML
    assert labels["books"]["language"]["05"] == "Swedish"  # 05 stays a string
    assert labels["loans"]["status"] == {"O": "Open", "R": "Returned", "L": "Late"}


def test_toy_schema_response_and_label_filtering(toy_package):
    response = toy_package.graph_dataset().to_schema_response()
    assert response.domain.name == "Lending Library" and response.domain.version == "1.0.0"
    book = next(n for n in response.node_types if n.key == "Book")
    assert book.value_labels == {"language": {"EN": "English", "NO": "Norwegian", "05": "Swedish"}}


def test_toy_works_through_the_api_with_a_dataset_selector(tmp_path):
    import shutil

    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        client = TestClient(app)
        body = client.get("/api/graph/schema", headers={"X-GraphSense-Dataset": "toy_library"}).json()
        assert body["domain"]["id"] == "toy_library"
        assert {n["key"] for n in body["node_types"]} == {"Author", "Book", "Member", "Loan"}
        assert _has_o2c(json.dumps(body)) == []
        flows = client.get("/api/graph/flows", params={"dataset": "toy_library"}).json()["flows"]
        assert [f["id"] for f in flows] == ["lending"]
        # the default dataset is unchanged
        assert client.get("/api/graph/schema").json()["domain"]["id"] == "o2c"
        assert client.get("/api/graph/schema", headers={"X-GraphSense-Dataset": "missing"}).status_code == 404


def test_default_dataset_can_be_switched_with_a_setting(tmp_path):
    import shutil

    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path, DEFAULT_DATASET="toy_library"):
        assert get_dataset().id == "toy_library"
        assert TestClient(app).get("/api/graph/schema").json()["domain"]["id"] == "toy_library"


# ---------------------------------------------------------------------------
# The engine itself
# ---------------------------------------------------------------------------

GENERIC_SOURCES = [
    *sorted((BACKEND_DIR / "src" / "datasets").glob("*.py")),
    *sorted((BACKEND_DIR / "src" / "catalog").glob("*.py")),
    *sorted((BACKEND_DIR / "src" / "cli").rglob("*.py")),
    BACKEND_DIR / "src" / "api" / "deps.py",
    BACKEND_DIR / "src" / "api" / "catalog.py",
    BACKEND_DIR / "src" / "api" / "errors.py",
    BACKEND_DIR / "src" / "domain" / "graph_schema.py",
    BACKEND_DIR / "src" / "domain" / "graph_models.py",
    BACKEND_DIR / "src" / "domain" / "graph_registry.py",
    BACKEND_DIR / "src" / "repositories" / "graph_sql.py",
    BACKEND_DIR / "src" / "repositories" / "graph_repository.py",
]


@pytest.mark.parametrize("path", GENERIC_SOURCES, ids=lambda p: str(Path(p).relative_to(BACKEND_DIR)))
def test_generic_engine_code_names_no_dataset(path):
    """No dataset names, table names or business vocabulary in the generic engine."""
    found = _has_o2c(path.read_text(encoding="utf-8"))
    assert found == [], f"{path.name} mentions {found}"


def test_the_only_default_dataset_name_lives_in_the_settings():
    text = (BACKEND_DIR / "src" / "config.py").read_text(encoding="utf-8")
    assert len(re.findall(r"\bo2c\b", text)) == 1  # the default of DEFAULT_DATASET
    assert get_package("o2c").id == "o2c"


def test_canon_still_normalises_whitespace():
    assert canon("SELECT  a ,\n b -- note\n FROM t") == "SELECT a,b FROM t"
