"""Turn a dataset package into the ``GraphDataset`` the graph layer runs on.

The graph model itself (node types, edge types, flows, entity hints) is read
from ``graph.yaml`` unchanged; the package adds its identity, version and the
labels of coded columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.graph_schema import GraphDataset

if TYPE_CHECKING:
    from src.datasets.models import DatasetPackage


def build_graph_dataset(pkg: DatasetPackage) -> GraphDataset:
    graph = pkg.graph
    return GraphDataset(
        id=pkg.id,
        name=pkg.name,
        description=pkg.description,
        node_types=graph.node_types,
        edge_types=graph.edge_types,
        flows=graph.flows,
        entity_column_hints=graph.entity_column_hints,
        entity_refs=graph.entity_refs,
        version=pkg.version,
        # Labels the author is not sure about (confidence: low) are not served to clients.
        value_labels=pkg.value_labels(min_confidence="medium"),
    )
