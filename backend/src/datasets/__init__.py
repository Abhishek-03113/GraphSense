"""Dataset packages: the declarative description of a dataset.

A package is a directory of YAML (tables, graph, semantics) validated by
pydantic.  Everything dataset-specific in the product - the database schema,
the graph, the catalog, the prompts and the evaluations - is derived from it.
This package contains the engine only: it knows nothing about any particular
dataset and needs no database.

Public API::

    get_package("<id>")           -> DatasetPackage (cached, validated)
    load_package(Path)            -> DatasetPackage (any directory)
    list_packages()               -> [PackageInfo]
    default_dataset_id()          -> str
    schema_ddl(pkg, "ds_<id>")    -> [CREATE statements]
    table_ddl(table, "ds_<id>")   -> CREATE TABLE
    row_coercer(table)            -> record -> (row tuple, issues)
"""

from src.datasets.coerce import RowIssue, row_coercer
from src.datasets.context import DatasetContext
from src.datasets.ddl import schema_ddl, table_ddl
from src.datasets.errors import LintIssue, PackageError, UnknownDatasetError
from src.datasets.loader import load_package
from src.datasets.models import DatasetPackage, TableSpec
from src.datasets.registry import (
    PackageInfo,
    clear_package_cache,
    default_dataset_id,
    get_package,
    list_packages,
)
from src.datasets.validate import LintReport, validate_package

__all__ = [
    "DatasetContext",
    "DatasetPackage",
    "LintIssue",
    "LintReport",
    "PackageError",
    "PackageInfo",
    "RowIssue",
    "TableSpec",
    "UnknownDatasetError",
    "clear_package_cache",
    "default_dataset_id",
    "get_package",
    "list_packages",
    "load_package",
    "row_coercer",
    "schema_ddl",
    "table_ddl",
    "validate_package",
]
