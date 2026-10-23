"""Where packages are found: the shipped directory, PACKAGES_DIR, and bad ids."""

import shutil

import pytest

from src.config import override_settings
from src.datasets import UnknownDatasetError, default_dataset_id, get_package, list_packages
from tests.conftest import TOY_DIR


def test_registry_finds_shipped_packages():
    assert default_dataset_id() == "o2c"
    assert "o2c" in {p.id for p in list_packages()}
    assert get_package("o2c") is get_package("o2c")  # cached


def test_registry_searches_packages_dir_first(tmp_path):
    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        assert get_package("toy_library").name == "Lending Library"
        assert {"o2c", "toy_library"} <= {p.id for p in list_packages()}


def test_unknown_or_malformed_ids_are_rejected():
    for bad in ("nope", "../etc", "o2c/../..", "O2C", "", "a b"):
        with pytest.raises(UnknownDatasetError):
            get_package(bad)


def test_a_broken_package_is_listed_with_its_error_and_does_not_hide_others(tmp_path, package_copy):
    broken = package_copy(edits={"tables/books.yaml": ("primary_key: [isbn]", "primary_key: [nope]")})
    shutil.move(str(broken), tmp_path / "toy_library_broken")  # directory name no longer matches: still listed
    (tmp_path / "toy_library_broken").rename(tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        infos = {p.id: p for p in list_packages()}
    assert infos["toy_library"].valid is False and infos["toy_library"].error
    assert infos["o2c"].valid is True

