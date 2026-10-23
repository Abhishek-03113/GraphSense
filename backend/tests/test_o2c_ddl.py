"""DDL generated for the reference (order-to-cash) package.

Regenerate the golden file after an intended change with::

    python -c "from src.cli.main import main; main(['package', 'ddl', 'o2c'])" > tests/fixtures/ddl/o2c.sql
"""

import re

from src.datasets import schema_ddl, table_ddl
from src.datasets.ddl import primary_key_name, table_indexes
from tests.conftest import FIXTURES


def _render(statements: list[str]) -> str:
    return "".join(statement + ";\n\n" for statement in statements)


def test_o2c_ddl_matches_the_golden_file(o2c_package):
    expected = (FIXTURES / "ddl" / "o2c.sql").read_text(encoding="utf-8")
    assert _render(schema_ddl(o2c_package, "ds_o2c")) == expected


def test_ddl_is_deterministic(o2c_package):
    assert schema_ddl(o2c_package, "ds_o2c") == schema_ddl(o2c_package, "ds_o2c")


def test_every_table_has_a_named_primary_key_and_real_types(o2c_package):
    assert len(o2c_package.tables) == 19
    for table in o2c_package.tables:
        sql = table_ddl(table, "ds_o2c")
        assert f'CONSTRAINT "{primary_key_name(table.table)}" PRIMARY KEY' in sql
        assert "varchar" not in sql.lower()
        for col in table.stored_columns():
            assert f'"{col.name}" {col.sql_type.ddl}' in sql


def test_graph_lookup_columns_are_indexed_once(o2c_package):
    sql = _render(schema_ddl(o2c_package, "ds_o2c"))
    # the target of FULFILLS: a composite index, not two single column ones
    assert re.search(r'ON "ds_o2c"\."outbound_delivery_items" \("reference_sd_document", "reference_sd_document_item"\)', sql)
    # an id column that is not the start of the primary key gets an index
    assert 'ON "ds_o2c"."payments_accounts_receivable" ("accounting_document")' in sql
    # the start of a primary key does not
    assert 'ON "ds_o2c"."sales_order_headers" ("sales_order")' not in sql
    names = re.findall(r'CREATE INDEX "([^"]+)"', sql)
    assert len(names) == len(set(names))


def test_declared_indexes_are_first_and_not_duplicated(o2c_package):
    table = o2c_package.table("sales_order_headers")
    assert table_indexes(o2c_package, table) == [("sold_to_party",)]

