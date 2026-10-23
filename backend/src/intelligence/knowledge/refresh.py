"""Bring the knowledge store in line with a dataset's current catalog.

The desired items are computed from the catalog snapshot.  Only items whose content
changed are embedded (a content hash decides), then new rows are inserted and
obsolete rows deleted in a single transaction, so a concurrent question never sees an
empty store.  Without an embedding model (or when it fails) items are stored as text
only, which full-text retrieval can still find.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from src.catalog import CatalogSnapshot
from src.intelligence.knowledge.items import KnowledgeItem, build_items
from src.intelligence.knowledge.store import KnowledgeStore, NewRow, StoredRow
from src.intelligence.providers.base import EmbeddingProvider, ProviderError, is_configured
from src.utils.logger import get_logger

logger = get_logger(__name__)

EMBED_BATCH = 64

State = Literal["ready", "stale", "missing"]


@dataclass
class RefreshReport:
    dataset_id: str
    items: int = 0
    inserted: int = 0
    deleted: int = 0
    kept: int = 0
    embedded: int = 0
    text_only: int = 0
    embed_model: str = ""
    # Why items were stored without an embedding ("" when all were embedded or no model is set).
    not_embedded_reason: str = ""
    duration_ms: int = 0
    state: State = "missing"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeStatus:
    state: State
    items: int
    embed_model: str
    embedded: int
    text_only: int

    def as_dict(self) -> dict:
        return asdict(self)


def summarise(rows: list[StoredRow], embed_model: str, desired: set[tuple[str, str]] | None = None) -> KnowledgeStatus:
    """``missing`` (no rows), ``stale`` (rows out of date or not yet embedded) or ``ready``."""
    if not rows:
        return KnowledgeStatus("missing", 0, embed_model, 0, 0)
    embedded = sum(1 for r in rows if r.has_embedding and r.embed_model == embed_model and embed_model)
    text_only = len(rows) - embedded
    stale = False
    if desired is not None and {(r.kind, r.content_hash) for r in rows} != desired:
        stale = True
    if embed_model and embedded < len(rows):
        stale = True
    return KnowledgeStatus("stale" if stale else "ready", len(rows), embed_model, embedded, text_only)


async def knowledge_status(
    store: KnowledgeStore,
    dataset_id: str,
    embedder: EmbeddingProvider,
    snapshot: CatalogSnapshot | None = None,
) -> KnowledgeStatus:
    model = embedder.model if is_configured(embedder) else ""
    rows = await store.existing(dataset_id)
    desired = {(i.kind, i.content_hash) for i in build_items(snapshot)} if snapshot is not None else None
    return summarise(rows, model, desired)


async def refresh_knowledge(
    store: KnowledgeStore,
    snapshot: CatalogSnapshot,
    embedder: EmbeddingProvider,
    *,
    force: bool = False,
) -> RefreshReport:
    started = time.perf_counter()
    dataset_id = snapshot.dataset_id
    items = build_items(snapshot)
    report = RefreshReport(dataset_id=dataset_id, items=len(items))
    model = embedder.model if is_configured(embedder) else ""
    report.embed_model = model

    existing = await store.existing(dataset_id)
    by_hash: dict[tuple[str, str], list[StoredRow]] = {}
    for row in existing:
        by_hash.setdefault((row.kind, row.content_hash), []).append(row)

    keep_ids: set[int] = set()
    pending: list[KnowledgeItem] = []
    for item in items:
        rows = by_hash.get((item.kind, item.content_hash), [])
        good = [r for r in rows if r.embed_model == model and (r.has_embedding or not model)]
        if good and not force:
            keep_ids.add(good[0].id)
            continue
        pending.append(item)

    new_rows: list[NewRow] = []
    vectors: dict[int, list[float]] = {}
    if model and pending:
        try:
            for start in range(0, len(pending), EMBED_BATCH):
                batch = pending[start : start + EMBED_BATCH]
                result = await embedder.embed([i.text for i in batch], task="document")
                for offset, vec in enumerate(result):
                    vectors[start + offset] = vec
        except ProviderError as exc:
            report.not_embedded_reason = type(exc).__name__
            report.warnings.append(f"embedding failed ({type(exc).__name__}); items stored as text only")
            logger.warning("Knowledge refresh could not embed items: %s", exc)
        except Exception as exc:
            report.not_embedded_reason = type(exc).__name__
            report.warnings.append("embedding failed unexpectedly; items stored as text only")
            logger.exception("Knowledge refresh could not embed items: %s", exc)
    elif not model and pending:
        report.not_embedded_reason = "no embedding model configured"

    dims_seen = {len(v) for v in vectors.values()}
    if len(dims_seen) > 1:
        report.warnings.append("embedding sizes differ; items stored as text only")
        vectors = {}

    for index, item in enumerate(pending):
        vec = vectors.get(index)
        siblings = by_hash.get((item.kind, item.content_hash), [])
        if vec is not None:
            new_rows.append(
                NewRow(item.kind, item.ref, item.text, item.content_hash, model, len(vec), vec, item.metadata)
            )
            report.embedded += 1
            continue
        # No embedding: keep a row that already carries this content, else store the text alone.
        if siblings and not force:
            keep_ids.add(siblings[0].id)
        else:
            new_rows.append(NewRow(item.kind, item.ref, item.text, item.content_hash, "", None, None, item.metadata))
            report.text_only += 1

    delete_ids = [r.id for r in existing if r.id not in keep_ids]
    report.kept = len(keep_ids)
    report.inserted = len(new_rows)
    report.deleted = len(delete_ids)
    # Insert and delete together: the store is never empty in between.
    await store.replace(dataset_id, new_rows, delete_ids)

    final = await store.existing(dataset_id)
    status = summarise(final, model, {(i.kind, i.content_hash) for i in items})
    report.state = status.state
    report.embedded = status.embedded
    report.text_only = status.text_only
    report.duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Knowledge refresh for %s: %d items, +%d -%d, %d embedded (%s)",
        dataset_id, report.items, report.inserted, report.deleted, report.embedded, report.state,
    )
    return report
