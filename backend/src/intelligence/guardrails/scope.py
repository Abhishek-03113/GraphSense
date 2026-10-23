"""Is the question about this dataset?

A question is in scope when either

* it uses a word from the dataset's *scope vocabulary* (the package's own terms and
  synonyms, plus words derived from table and column names, node labels, coded-value
  labels and glossary titles), or
* its best retrieval similarity to the dataset's knowledge reaches
  ``vocabulary.min_similarity`` (needs an embedding model).

There is no "looks like an analytical question" shortcut: asking to *list* or *show*
something says nothing about the subject.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.catalog import CatalogSnapshot
from src.datasets.models import DatasetPackage
from src.intelligence.catalog_access import llm_safe
from src.intelligence.text import STOPWORDS, stem, words

# Words that appear in column names of almost any dataset and say nothing about the subject.
GENERIC_WORDS = frozenset(
    ["id", "ids", "key", "keys", "name", "names", "type", "types", "code", "codes", "status", "date", "dates", "time", "times", "number", "numbers", "no", "amount", "amounts", "value", "values", "total", "totals", "count", "counts", "text", "description", "descriptions", "flag", "group", "groups", "category", "unit", "units", "item", "items", "info", "information", "data", "record", "records", "field", "fields", "created", "creation", "changed", "change", "last", "first", "update", "updated", "user", "users", "by", "at", "on", "year", "month", "day", "week", "period", "class", "kind", "reference", "ref", "line", "lines", "sum", "average", "avg", "min", "max", "rate"]
)

# Questions about the data itself are always in scope.
META_WORDS = frozenset(
    ["dataset", "data", "database", "table", "column", "schema", "record", "entity", "relationship", "graph", "node", "edge", "overview", "summary", "describe", "structure", "field"]
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _split(text: str) -> list[str]:
    return words(_CAMEL.sub(" ", text))


@dataclass
class ScopeVocabulary:
    strong: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, package: DatasetPackage, snapshot: CatalogSnapshot) -> ScopeVocabulary:
        safe = llm_safe(snapshot)
        vocab = cls()

        def add(text: str, *, generic_ok: bool = False) -> None:
            for w in _split(text):
                s = stem(w)
                if len(s) < 3 or w in STOPWORDS:
                    continue
                if not generic_ok and (w in GENERIC_WORDS or s in GENERIC_WORDS):
                    continue
                vocab.strong.add(s)

        v = package.vocabulary
        for term in v.terms:
            add(term, generic_ok=True)
        for key, alternatives in v.synonyms.items():
            add(key, generic_ok=True)
            for alt in alternatives:
                add(alt, generic_ok=True)
        add(package.name)
        for node in package.graph.node_types:
            add(node.key)
            add(node.label)
            add(node.plural)
        for table in safe.tables:
            add(table.name)
            for col in table.columns:
                if not col.hidden:
                    add(col.name)
                for label in col.value_labels.values():
                    add(label)
        for entry in safe.glossary:
            add(entry.title)
        return vocab

    def matches(self, question: str) -> list[str]:
        found = []
        for w in words(question):
            s = stem(w)
            if s in self.strong and s not in found or s in META_WORDS and s not in found:
                found.append(s)
        return found


@dataclass(frozen=True)
class ScopeDecision:
    in_scope: bool
    reason: str  # "vocabulary" | "similarity" | "out_of_scope"
    matched: tuple[str, ...] = ()
    similarity: float | None = None


def decide(
    vocabulary: ScopeVocabulary,
    question: str,
    *,
    best_similarity: float | None,
    min_similarity: float,
) -> ScopeDecision:
    matched = vocabulary.matches(question)
    if matched:
        return ScopeDecision(True, "vocabulary", tuple(matched), best_similarity)
    if best_similarity is not None and best_similarity >= min_similarity:
        return ScopeDecision(True, "similarity", (), best_similarity)
    return ScopeDecision(False, "out_of_scope", (), best_similarity)
