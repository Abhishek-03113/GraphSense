"""Small text helpers shared by retrieval and the scope check (no dependencies, no dataset knowledge)."""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    ["a", "about", "above", "after", "again", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "me", "more", "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "us", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "show", "give", "tell", "list", "find", "get", "display", "please", "many", "much"]
)


def stem(word: str) -> str:
    """A very light plural stripper: ``books`` -> ``book``, ``companies`` -> ``company``."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """Lower-case alphanumeric words; underscores and punctuation separate words."""
    return _WORD.findall(text.lower())


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Stemmed words of ``text`` without stop words, in order (repeats kept)."""
    out = []
    for word in words(text):
        if drop_stopwords and word in STOPWORDS:
            continue
        out.append(stem(word))
    return out


def clip(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` characters at a word boundary, with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)].rsplit(" ", 1)[0]
    return cut.rstrip(",.;: ") + "…"
