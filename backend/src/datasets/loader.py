"""Load a dataset package from its directory of YAML files.

Layout::

    <package>/
      package.yaml              manifest
      tables/<table>.yaml       one file per table
      graph.yaml                node types, edge types, flows, entity refs
      semantics/<name>.yaml     value_sets, glossary, relationships, hints,
                                examples, vocabulary, suggested_questions

Nothing in a package executes: files are parsed with a restricted YAML loader
and validated by the pydantic models in ``src/datasets/models.py``.

YAML pitfalls (the "Norway problem": ``NO`` read as false, ``05`` read as an
octal number, ``0003`` as an integer) are avoided by a loader that does not
interpret numbers or the YAML 1.1 boolean words at all.  Every plain scalar
arrives as a string, except ``true``/``false`` (booleans) and ``null``/``~``/
empty (null).  Pydantic's lax mode then converts strings to the declared
field type (``min_rows: 3`` becomes the integer 3), while a code such as
``0003`` or ``N`` in a value set stays exactly what was written.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError
from yaml.constructor import ConstructorError

from src.datasets.errors import LintIssue, PackageError
from src.datasets.models import (
    DatasetPackage,
    ExampleSpec,
    GlossaryEntry,
    GraphSpec,
    RelationshipSpec,
    Semantics,
    SuggestedQuestion,
    TableSpec,
    ValueSet,
    Vocabulary,
)

MANIFEST_FILE = "package.yaml"
MAX_FILE_BYTES = 2_000_000

# Which semantic file feeds which field of ``Semantics``, and how it is parsed.
# Each entry: file stem -> (field, annotation, value of an empty file).
_SEMANTIC_FILES: dict[str, tuple[str, Any, Any]] = {
    "value_sets": ("value_sets", dict[str, ValueSet], {}),
    "glossary": ("glossary", list[GlossaryEntry], []),
    "relationships": ("relationships", list[RelationshipSpec], []),
    "hints": ("hints", list[str], []),
    "examples": ("examples", list[ExampleSpec], []),
    "vocabulary": ("vocabulary", Vocabulary, {}),
    "suggested_questions": ("suggested_questions", list[SuggestedQuestion], []),
}
_MANIFEST_FORBIDDEN = ("tables", "graph", "semantics")


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that leaves numbers and YAML 1.1 words (yes/no/on/off) as plain strings."""


_StrictLoader.yaml_implicit_resolvers = {}
_StrictLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))
_StrictLoader.add_implicit_resolver("tag:yaml.org,2002:null", re.compile(r"^(?:~|null|)$"), ["~", "n", ""])


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if isinstance(key, list | dict):
            continue  # reported by the base implementation
        if key in seen:
            raise ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.construct_mapping = _construct_mapping  # type: ignore[method-assign]


def load_yaml_text(text: str) -> Any:
    """Parse YAML with the strict loader (see the module docstring)."""
    return yaml.load(text, Loader=_StrictLoader)


def _read_yaml(path: Path, root: Path, issues: list[LintIssue]) -> tuple[bool, Any]:
    """Read one file; returns ``(ok, data)`` and records problems in ``issues``."""
    rel = path.relative_to(root).as_posix()
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            issues.append(LintIssue("file_too_large", f"larger than {MAX_FILE_BYTES} bytes", rel))
            return False, None
        return True, load_yaml_text(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        issues.append(LintIssue("yaml", _one_line(str(exc)), rel))
        return False, None


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _validation_issues(exc: ValidationError, where: str) -> list[LintIssue]:
    issues = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(part) for part in err["loc"])
        issues.append(LintIssue("schema", f"{loc}: {err['msg']}" if loc else err["msg"], where))
    return issues


def _resolve_package_dir(path: Path) -> Path:
    path = Path(path)
    if path.is_file() and path.name == MANIFEST_FILE:
        path = path.parent
    if not (path / MANIFEST_FILE).is_file():
        raise PackageError(f"{path} is not a dataset package: {MANIFEST_FILE} not found")
    return path.resolve()


def _included_files(root: Path, patterns: tuple[str, ...], issues: list[LintIssue]) -> list[Path]:
    files: dict[Path, None] = {}
    for pattern in patterns:
        for candidate in sorted(root.glob(pattern)):
            if candidate.suffix not in (".yaml", ".yml") or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                issues.append(
                    LintIssue("path_escape", "included file resolves outside the package directory",
                              candidate.relative_to(root).as_posix())
                )
                continue
            files[resolved] = None
    return list(files)


def load_package(path: Path, *, lint: bool = True) -> DatasetPackage:
    """Load, validate and return the package in ``path``.

    Raises :class:`PackageError` listing every problem found.  With ``lint=False``
    only structural (schema) validation runs; the cross-reference checks of
    :func:`src.datasets.validate.validate_package` are skipped.
    """
    root = _resolve_package_dir(path)
    issues: list[LintIssue] = []

    ok, manifest = _read_yaml(root / MANIFEST_FILE, root, issues)
    if not ok:
        raise PackageError(f"cannot read {MANIFEST_FILE} of {root.name}", issues)
    if not isinstance(manifest, dict):
        raise PackageError(f"{MANIFEST_FILE} of {root.name} must be a mapping", issues)
    for key in _MANIFEST_FORBIDDEN:
        if key in manifest:
            issues.append(LintIssue("manifest", f"{key!r} belongs in its own file, not in {MANIFEST_FILE}", MANIFEST_FILE))

    includes = manifest.get("includes")
    patterns = tuple(includes) if isinstance(includes, list) else ("tables/*.yaml", "graph.yaml", "semantics/*.yaml")
    tables: list[TableSpec] = []
    graph_data: Any = None
    semantic_data: dict[str, Any] = {}

    for file in _included_files(root, tuple(str(p) for p in patterns), issues):
        rel = file.relative_to(root)
        where = rel.as_posix()
        ok, data = _read_yaml(file, root, issues)
        if not ok:
            continue
        parts = rel.parts
        try:
            if len(parts) == 2 and parts[0] == "tables":
                spec = TableSpec.model_validate(data)
                if spec.table != rel.stem:
                    issues.append(LintIssue("table_file_name", f"declares table {spec.table!r}; name the file {spec.table}.yaml", where))
                tables.append(spec)
            elif rel.as_posix() == "graph.yaml":
                graph_data = GraphSpec.model_validate(data if data is not None else {})
            elif len(parts) == 2 and parts[0] == "semantics" and rel.stem in _SEMANTIC_FILES:
                field, annotation, empty = _SEMANTIC_FILES[rel.stem]
                semantic_data[field] = TypeAdapter(annotation).validate_python(data if data is not None else empty)
            else:
                issues.append(LintIssue("unknown_file", "included file has no known role (tables/, graph.yaml, semantics/<name>.yaml)", where))
        except ValidationError as exc:
            issues.extend(_validation_issues(exc, where))

    if issues:
        raise PackageError(f"dataset package {root.name!r} is invalid", issues)

    try:
        package = DatasetPackage.model_validate(
            {
                **manifest,
                "tables": tables,
                "graph": graph_data or GraphSpec(),
                "semantics": Semantics(**semantic_data),
            }
        )
    except ValidationError as exc:
        raise PackageError(f"dataset package {root.name!r} is invalid", _validation_issues(exc, MANIFEST_FILE)) from None

    if package.id != root.name:
        raise PackageError(
            f"dataset package {root.name!r} is invalid",
            [LintIssue("package_id", f"id {package.id!r} must equal the directory name {root.name!r}", MANIFEST_FILE)],
        )
    package._path = root

    if lint:
        from src.datasets.validate import validate_package

        report = validate_package(package)
        if report.errors:
            raise PackageError(f"dataset package {package.id!r} failed validation", list(report.errors))
    return package
