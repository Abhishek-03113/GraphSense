"""``AskService``: answer a natural-language question about one dataset.

This is the single entry point of the Ask layer.  Callers (the HTTP endpoint,
the evaluation harness, the CLI) hand it a :class:`DatasetContext` and a
question and get an :class:`AskResult`; they never talk to providers, the
database or the knowledge store directly.
"""

from __future__ import annotations

from src.datasets.context import DatasetContext
from src.intelligence.catalog_access import CatalogSource
from src.intelligence.models import AskResult
from src.intelligence.providers.base import EmbeddingProvider, LLMProvider


class AskService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        catalog: CatalogSource,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.catalog = catalog

    async def ask(
        self,
        ctx: DatasetContext,
        question: str,
        *,
        trace: bool = False,
        client_id: str | None = None,
    ) -> AskResult:
        """Answer ``question`` about the dataset ``ctx``.

        Never raises for expected failures (out of scope, no model key, a query
        that cannot run): those come back as an ``AskResult`` with ``error_code``
        set.  ``trace=True`` adds retrieval and attempt detail for evaluation.
        """
        raise NotImplementedError
