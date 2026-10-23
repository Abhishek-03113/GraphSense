"""In-memory text search over knowledge items (BM25-style), used when the store has no rows.

This keeps Ask working before the first knowledge refresh, when the database table is
missing, and in unit tests.  It ranks the same items the database full-text search would.
"""

from __future__ import annotations

import math
from collections import Counter

from src.intelligence.knowledge.items import KnowledgeItem
from src.intelligence.knowledge.store import Hit
from src.intelligence.text import tokens

K1 = 1.4
B = 0.75


class InMemoryIndex:
    def __init__(self, items: list[KnowledgeItem]) -> None:
        self.items = items
        self._docs: list[Counter[str]] = []
        for item in items:
            counts = Counter(tokens(item.text))
            # The reference (a table or entry name) is a strong signal of what the item is about.
            for token in tokens(item.ref):
                counts[token] += 2
            self._docs.append(counts)
        self._lengths = [sum(c.values()) for c in self._docs]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        frequency: Counter[str] = Counter()
        for counts in self._docs:
            frequency.update(counts.keys())
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}

    def search(self, question: str, limit: int) -> list[Hit]:
        query = list(dict.fromkeys(tokens(question)))
        scored: list[tuple[float, int]] = []
        for index, counts in enumerate(self._docs):
            length = self._lengths[index] or 1
            score = 0.0
            for term in query:
                tf = counts.get(term, 0)
                if tf:
                    score += self._idf.get(term, 0.0) * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self._avg))
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [
            Hit(self.items[i].kind, self.items[i].ref, self.items[i].text, dict(self.items[i].metadata), score)
            for score, i in scored[:limit]
        ]
