"""``GET /api/datasets/{id}/catalog``: what a dataset's tables and columns hold."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.catalog.model import CatalogSnapshot
from src.catalog.safety import strip_sensitive_values
from src.catalog.service import CatalogService, CatalogStatus, get_catalog_service
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import get_package

router = APIRouter(prefix="/api/datasets", tags=["catalog"])


class ValueCountOut(BaseModel):
    value: str
    count: int | None = None
    label: str | None = None


class ColumnOut(BaseModel):
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    role: str | None = None
    description: str = ""
    is_pk: bool = False
    sensitive: bool = False
    hidden: bool = False
    value_set: str | None = None
    value_labels: dict[str, str] = {}
    currency_column: str | None = None
    refs: str | None = None
    # Profile statistics; null until the catalog is built.  Never any value for sensitive columns.
    null_rate: float | None = None
    distinct_count: int | None = None
    min_value: str | None = None
    max_value: str | None = None
    top_values: list[ValueCountOut] = []
    sample_values: list[str] = []


class TableOut(BaseModel):
    name: str
    description: str = ""
    grain: str | None = None
    primary_key: list[str] = []
    row_count: int | None = None
    node_type: str | None = None
    columns: list[ColumnOut]


class RelationshipOut(BaseModel):
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]
    kind: Literal["graph_edge", "declared"]
    cardinality: str | None = None
    expression: str = ""
    description: str = ""
    match_rate: float | None = None
    coverage: float | None = None


class DriftOut(BaseModel):
    kind: str
    severity: Literal["error", "warning"]
    table: str
    column: str | None = None
    message: str


class BuildOut(BaseModel):
    origin: Literal["stored", "live", "package"]
    run_id: str | None = None
    built_at: datetime | None = None
    duration_ms: int | None = None
    profile_sample_rows: int | None = None
    # The package was edited after the catalog was built.
    stale: bool = False
    notes: list[str] = []
    drift: list[DriftOut] = []


class CatalogOut(BaseModel):
    dataset_id: str
    name: str
    description: str
    package_version: str
    build: BuildOut
    tables: list[TableOut]
    relationships: list[RelationshipOut]


def catalog_payload(snapshot: CatalogSnapshot, status: CatalogStatus) -> CatalogOut:
    """The API shape of a snapshot.  Values of sensitive columns are removed whatever the snapshot holds."""
    safe = strip_sensitive_values(snapshot)
    tables = [
        TableOut(
            name=t.name,
            description=t.description,
            grain=t.grain,
            primary_key=list(t.primary_key),
            row_count=t.row_count,
            node_type=t.node_type,
            columns=[
                ColumnOut(
                    name=c.name,
                    ordinal=c.ordinal,
                    data_type=c.data_type,
                    nullable=c.nullable,
                    role=c.role,
                    description=c.description,
                    is_pk=c.is_pk,
                    sensitive=c.sensitive,
                    hidden=c.hidden,
                    value_set=c.value_set,
                    value_labels=c.value_labels,
                    currency_column=c.currency_column,
                    refs=c.refs,
                    null_rate=c.null_rate,
                    distinct_count=c.distinct_count,
                    min_value=c.min_value,
                    max_value=c.max_value,
                    top_values=[ValueCountOut(value=v.value, count=v.count, label=v.label) for v in c.top_values],
                    sample_values=list(c.sample_values),
                )
                for c in t.columns
            ],
        )
        for t in safe.tables
    ]
    relationships = [
        RelationshipOut(
            from_table=r.from_table,
            from_columns=list(r.from_columns),
            to_table=r.to_table,
            to_columns=list(r.to_columns),
            kind=r.kind,
            cardinality=r.cardinality,
            expression=r.expression,
            description=r.description,
            match_rate=r.match_rate,
            coverage=r.coverage,
        )
        for r in safe.relationships
    ]
    build = BuildOut(
        origin=status.origin,
        run_id=status.run_id,
        built_at=status.built_at,
        duration_ms=status.duration_ms,
        profile_sample_rows=status.profile_sample_rows,
        stale=status.stale,
        notes=list(status.notes),
        drift=[
            DriftOut(kind=d.kind, severity=d.severity, table=d.table, column=d.column, message=d.message)
            for d in status.drift
        ],
    )
    return CatalogOut(
        dataset_id=safe.dataset_id,
        name=safe.name,
        description=safe.description,
        package_version=safe.package_version,
        build=build,
        tables=tables,
        relationships=relationships,
    )


@router.get("/{dataset_id}/catalog", response_model=CatalogOut)
async def get_catalog(
    dataset_id: str, service: Annotated[CatalogService, Depends(get_catalog_service)]
) -> CatalogOut:
    """Tables, columns (with coded values labelled), relationships with measured match rates, and drift.

    Columns marked sensitive in the dataset package carry no example values.
    """
    try:
        get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    snapshot = await service.get_snapshot(dataset_id)
    status = await service.get_status(dataset_id)
    return catalog_payload(snapshot, status)
