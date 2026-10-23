"""Shared FastAPI dependencies."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import default_dataset_id, get_package
from src.db.session import get_db_session
from src.storage.session import use_dataset

DATASET_HEADER = "X-GraphSense-Dataset"


async def get_dataset_context(
    dataset_header: str | None = Header(default=None, alias=DATASET_HEADER),
    dataset: str | None = Query(default=None, description="Dataset id (default: the deployment's default dataset)"),
) -> DatasetContext:
    """The dataset a request is about: ``X-GraphSense-Dataset`` header, ``?dataset=``, or the default.

    An unknown id answers 404.  ``schema_name`` is the schema the dataset's
    tables live in (``ds_<id>``); see :func:`get_dataset_db` for how requests
    read it.  A database that still keeps the tables in ``public`` works too,
    because ``public`` stays on the search path behind the dataset schema.
    """
    dataset_id = dataset_header or dataset or default_dataset_id()
    try:
        package = get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    return DatasetContext(id=package.id, schema_name=package.schema_name, package=package)


async def get_dataset_db(
    ctx: DatasetContext = Depends(get_dataset_context),
    db: AsyncSession = Depends(get_db_session),
) -> AsyncIterator[AsyncSession]:
    """The request's database session, scoped to the dataset's schema.

    The search path is set for the current transaction only, so a pooled
    connection never leaks one request's dataset into the next.
    """
    await use_dataset(db, ctx)
    yield db


_bearer_prefix = "bearer "


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


async def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Operator authentication: ``Authorization: Bearer <ADMIN_TOKEN>``.

    The routes using this are only mounted when a token is configured; if the
    token disappears at runtime they answer 404 like any unknown route.  The
    comparison is constant time (over fixed-length digests, so the token length
    does not leak either).
    """
    expected = get_settings().GRAPHSENSE_ADMIN_TOKEN
    if expected is None:
        raise HTTPException(status_code=404, detail="Not Found")
    supplied = ""
    if authorization and authorization.lower().startswith(_bearer_prefix):
        supplied = authorization[len(_bearer_prefix):].strip()
    if not supplied or not secrets.compare_digest(_digest(supplied), _digest(expected.get_secret_value())):
        raise HTTPException(
            status_code=401, detail="Invalid or missing admin token.", headers={"WWW-Authenticate": "Bearer"}
        )
