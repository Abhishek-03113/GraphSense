"""DDL generated from packages: golden files, naming and safety.

Regenerate a golden file after an intended change with::

    python -c "from src.cli.main import main; main(['package', 'ddl', 'o2c'])" > tests/fixtures/ddl/o2c.sql
"""


import pytest

from src.datasets import schema_ddl, table_ddl
from src.datasets.ddl import (
    check_schema_name,
    index_name,
    primary_key_name,
    quote_ident,
)
from tests.conftest import FIXTURES


def _render(statements: list[str]) -> str:
    return "".join(statement + ";\n\n" for statement in statements)




def test_toy_ddl_matches_the_golden_file(toy_package):
    expected = (FIXTURES / "ddl" / "toy_library.sql").read_text(encoding="utf-8")
    assert _render(schema_ddl(toy_package, "ds_toy_library")) == expected






def test_primary_key_columns_are_not_null_and_other_columns_are_nullable(toy_package):
    sql = table_ddl(toy_package.table("loans"), "s")
    assert '"loan_id" text NOT NULL' in sql
    assert '"loaned_on" date NOT NULL' in sql  # required: true
    assert '"due_on" date,' in sql


def test_types_are_rendered_for_postgresql(toy_package):
    sql = table_ddl(toy_package.table("loans"), "s")
    assert '"returned_at" timestamptz' in sql
    assert '"late_fee" numeric(8,2)' in sql
    assert '"page_count" integer' in table_ddl(toy_package.table("books"), "s")
    assert '"is_reference" boolean' in table_ddl(toy_package.table("books"), "s")






def test_names_fit_postgresql_and_stay_stable():
    long = "t" * 60
    assert len(primary_key_name(long)) <= 63
    name = index_name(long, ("a", "b"))
    assert len(name) <= 63 and name == index_name(long, ("a", "b"))
    assert index_name(long, ("a", "b")) != index_name(long, ("a", "c"))


@pytest.mark.parametrize("bad", ["a;b", 'a"b', "A", "1a", "a b", "", "public.x", "a" * 64])
def test_unsafe_names_are_refused(bad):
    with pytest.raises(ValueError):
        quote_ident(bad)
    with pytest.raises(ValueError):
        check_schema_name(bad)


def test_schema_ddl_refuses_an_unsafe_schema_name(toy_package):
    with pytest.raises(ValueError):
        schema_ddl(toy_package, 'x"; DROP SCHEMA public; --')


def test_keep_raw_adds_a_hidden_text_column(package_copy):
    from src.datasets import load_package

    path = package_copy(edits={"tables/loans.yaml": ("normalize: [strip_leading_zeros],", "normalize: [strip_leading_zeros], keep_raw: true,")})
    loans = load_package(path).table("loans")
    names = [c.name for c in loans.stored_columns()]
    assert names[-1] == "copy_number_raw"
    assert '"copy_number_raw" text' in table_ddl(loans, "s")
