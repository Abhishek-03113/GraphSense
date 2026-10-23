"""Where dataset packages live and how they are looked up.

Packages are searched in order:

1. ``PACKAGES_DIR`` (setting) - an operator-managed directory outside the
   repository, for packages that must not be committed;
2. ``backend/dataset_packages`` - the packages shipped with the application.

The first directory containing ``<id>/package.yaml`` wins, so a deployment can
override a shipped package.  Loaded packages are cached per process.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from src.config import BACKEND_DIR, get_settings
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.loader import MANIFEST_FILE, load_package
from src.datasets.models import DatasetPackage

BUILTIN_PACKAGES_DIR = BACKEND_DIR / "dataset_packages"
_ID = re.compile(r"^[a-z][a-z0-9_]{0,30}$")

_lock = threading.Lock()
_cache: dict[tuple[str, str], DatasetPackage] = {}


@dataclass(frozen=True)
class PackageInfo:
    """Light description of an available package (see :func:`list_packages`)."""

    id: str
    name: str
    description: str
    version: str
    path: Path
    content_hash: str
    valid: bool = True
    error: str | None = None


def package_roots() -> list[Path]:
    """Directories searched for packages, highest priority first."""
    roots: list[Path] = []
    configured = get_settings().PACKAGES_DIR
    if configured is not None:
        roots.append(Path(configured))
    roots.append(BUILTIN_PACKAGES_DIR)
    return roots


def find_package_dir(dataset_id: str) -> Path:
    if not isinstance(dataset_id, str) or not _ID.match(dataset_id):
        raise UnknownDatasetError(f"Unknown dataset {dataset_id!r}")
    for root in package_roots():
        candidate = root / dataset_id
        if (candidate / MANIFEST_FILE).is_file():
            return candidate
    raise UnknownDatasetError(
        f"Unknown dataset {dataset_id!r}. Available: {', '.join(available_ids()) or 'none'}"
    )


def available_ids() -> list[str]:
    """Ids of every directory that looks like a package, without loading them."""
    ids: set[str] = set()
    for root in package_roots():
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if _ID.match(child.name) and (child / MANIFEST_FILE).is_file():
                ids.add(child.name)
    return sorted(ids)


def get_package(dataset_id: str) -> DatasetPackage:
    """The loaded, validated package for ``dataset_id`` (cached).

    Raises :class:`UnknownDatasetError` for an unknown id and
    :class:`PackageError` for a package that does not validate.
    """
    directory = find_package_dir(dataset_id)
    key = (dataset_id, str(directory.resolve()))
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    package = load_package(directory)
    with _lock:
        return _cache.setdefault(key, package)


def clear_package_cache() -> None:
    with _lock:
        _cache.clear()


def list_packages() -> list[PackageInfo]:
    """Every available package; a package that fails validation is listed with its error."""
    infos: list[PackageInfo] = []
    for dataset_id in available_ids():
        directory = find_package_dir(dataset_id)
        try:
            pkg = get_package(dataset_id)
        except PackageError as exc:
            first = str(exc).splitlines()[0]
            infos.append(PackageInfo(dataset_id, dataset_id, "", "", directory, "", valid=False, error=first))
            continue
        infos.append(
            PackageInfo(pkg.id, pkg.name, pkg.description, pkg.version, directory, pkg.content_hash)
        )
    return infos


def default_dataset_id() -> str:
    """The dataset used when a request does not name one (``DEFAULT_DATASET``)."""
    return get_settings().DEFAULT_DATASET
