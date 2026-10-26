"""Generated statements run on the driver: ``:name`` parameters become ``$n``, casts stay."""

from src.datasets.registry import get_package
from src.repositories.graph_sql import GraphSqlBuilder
from src.storage.session import positional


def test_parameters_are_numbered_in_order_of_first_use():
    sql, names = positional("SELECT a FROM t WHERE a = ANY(CAST(:ids AS text[])) AND b = :x LIMIT :limit OFFSET :ids")
    assert sql == "SELECT a FROM t WHERE a = ANY(CAST($1 AS text[])) AND b = $2 LIMIT $3 OFFSET $1"
    assert names == ("ids", "x", "limit")


def test_casts_and_literals_are_left_alone():
    sql, names = positional("SELECT x.a::text, 'Customer'::text AS t, (x.a::text || '-' || x.b::text) FROM x")
    assert names == () and "$" not in sql


def test_every_generated_graph_statement_converts_cleanly():
    builder = GraphSqlBuilder(get_package("o2c").graph_dataset())
    statements = [builder.summary_query()]
    statements += [builder.entities_query(n) for n in builder.dataset.node_types]
    for node in builder.dataset.node_types:
        statements.append(builder.details_query(node, ["1-2"])[0])
    keys = builder.dataset.node_keys
    statements.append(builder.neighbours_query({k: ["1"] for k in keys})[0])
    statements.append(builder.edges_between_query({k: ["1"] for k in keys})[0])
    for sql in statements:
        converted, names = positional(sql)
        assert ":" not in converted.replace("::", ""), sql
        assert len(set(names)) == len(names)
