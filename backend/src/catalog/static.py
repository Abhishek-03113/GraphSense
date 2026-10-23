"""Build a catalog snapshot from a dataset package alone (no database)."""

from __future__ import annotations

from src.catalog.model import (
    CatalogSnapshot,
    ColumnInfo,
    ExampleInfo,
    GlossaryEntry,
    RelationshipInfo,
    TableInfo,
)
from src.datasets.models import DatasetPackage, TableSpec
from src.datasets.normalizers import NORMALIZER_DESCRIPTIONS
from src.datasets.relationships import package_relationships


def _columns(pkg: DatasetPackage, table: TableSpec) -> tuple[ColumnInfo, ...]:
    pk = set(table.primary_key)
    out: list[ColumnInfo] = []
    for ordinal, col in enumerate(table.stored_columns(), start=1):
        spec = col.spec
        if col.is_raw:
            out.append(
                ColumnInfo(
                    table=table.table,
                    name=col.name,
                    ordinal=ordinal,
                    data_type=str(col.sql_type),
                    description=f"Original text of {spec.name} as it arrived, before normalisation.",
                    hidden=True,
                    sensitive=spec.sensitive,
                )
            )
            continue
        found = pkg.value_set_of(table.table, spec.name)
        out.append(
            ColumnInfo(
                table=table.table,
                name=spec.name,
                ordinal=ordinal,
                data_type=str(col.sql_type),
                nullable=col.nullable,
                role=spec.role,
                description=spec.description,
                is_pk=spec.name in pk,
                sensitive=spec.sensitive,
                hidden=spec.hidden,
                value_set=found[0] if found else None,
                value_labels=dict(found[1].values) if found else {},
                label_confidence=found[1].confidence if found else None,
                currency_column=spec.currency_column,
                refs=spec.refs,
                normalize=spec.normalize,
            )
        )
    return tuple(out)


def _normalisation_glossary(pkg: DatasetPackage) -> list[GlossaryEntry]:
    """One entry per table that normalises columns, with one sentence per column."""
    entries = []
    for table in pkg.tables:
        sentences = []
        for col in table.columns:
            if not col.normalize:
                continue
            how = ", ".join(NORMALIZER_DESCRIPTIONS[n] for n in col.normalize)
            sentence = f"{table.table}.{col.name} is {how}."
            if col.role == "item_number":
                sentence += " Item numbers have one canonical form in every table, so they can be compared directly."
            sentences.append(sentence)
        if sentences:
            entries.append(
                GlossaryEntry(
                    id=f"normalisation_{table.table}",
                    title=f"Normalised columns of {table.table}",
                    text=" ".join(sentences),
                    tables=(table.table,),
                    tags=("normalisation", "generated"),
                )
            )
    return entries


def snapshot_from_package(pkg: DatasetPackage) -> CatalogSnapshot:
    node_by_table = {}
    for node in pkg.graph.node_types:
        node_by_table.setdefault(node.table, node.key)

    tables = tuple(
        TableInfo(
            name=t.table,
            description=t.description,
            grain=t.grain,
            primary_key=t.primary_key,
            node_type=node_by_table.get(t.table),
            columns=_columns(pkg, t),
        )
        for t in pkg.tables
    )
    relationships = tuple(
        RelationshipInfo(
            from_table=j.from_table,
            from_columns=j.from_columns,
            to_table=j.to_table,
            to_columns=j.to_columns,
            kind=j.kind,
            cardinality=j.cardinality,
            expression=j.expression,
            description=j.description,
        )
        for j in package_relationships(pkg)
    )
    glossary = tuple(
        GlossaryEntry(g.id, g.title, g.text, g.tables, g.tags) for g in pkg.semantics.glossary
    ) + tuple(_normalisation_glossary(pkg))
    examples = tuple(
        ExampleInfo(e.id, e.question, e.sql, e.role, e.tags) for e in pkg.semantics.examples
    )
    return CatalogSnapshot(
        dataset_id=pkg.id,
        name=pkg.name,
        description=pkg.description,
        package_version=pkg.version,
        package_hash=pkg.content_hash,
        tables=tables,
        relationships=relationships,
        glossary=glossary,
        examples=examples,
        hints=pkg.semantics.hints,
        vocabulary=pkg.semantics.vocabulary,
    )
