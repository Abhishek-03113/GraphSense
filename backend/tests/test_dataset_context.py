"""Per-request dataset selection (header or query), defaulting to the configured dataset."""

import shutil

import pytest
from fastapi import HTTPException

from src.api.deps import get_dataset_context
from src.config import override_settings
from tests.conftest import TOY_DIR


async def test_default_dataset():
    ctx = await get_dataset_context(None, None)
    assert ctx.id == "o2c" and ctx.package.id == "o2c"
    assert ctx.schema_name == "ds_o2c"  # the dataset schema; public stays on the search path


async def test_header_wins_over_query_and_default(tmp_path):
    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        assert (await get_dataset_context("toy_library", "o2c")).id == "toy_library"
        assert (await get_dataset_context(None, "toy_library")).id == "toy_library"
        assert (await get_dataset_context(None, None)).id == "o2c"


async def test_unknown_dataset_is_a_404():
    with pytest.raises(HTTPException) as info:
        await get_dataset_context("nope", None)
    assert info.value.status_code == 404


async def test_malformed_dataset_ids_are_a_404_not_a_path_lookup():
    for bad in ("../etc", "o2c/..", "O2C", "a b"):
        with pytest.raises(HTTPException) as info:
            await get_dataset_context(bad, None)
        assert info.value.status_code == 404
