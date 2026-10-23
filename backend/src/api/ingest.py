"""``POST /api/ingest`` is gone.

It used to accept a directory path from the client and load it into the
database without authentication.  Loading data is an operator task now: use
``graphsense ingest <dataset>`` on the server, or the token-protected
``POST /api/admin/datasets/{id}/ingest``.  The route stays only to answer
clearly (410) instead of 404.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

GONE_DETAIL = (
    "Loading data from the API with a client-supplied path was removed. "
    "Operators run `graphsense ingest <dataset>` or use POST /api/admin/datasets/{id}/ingest."
)


@router.post("", include_in_schema=False)
async def ingestion_removed():
    raise HTTPException(status_code=410, detail=GONE_DETAIL)
