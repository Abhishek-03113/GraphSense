"""Generic, dataset-independent screening of a question before it reaches any model.

This is a fast first filter for prompt-injection phrasing and for questions that ask
for data to be changed.  It is not the SQL safety layer: whatever the model writes is
checked by ``SqlGuard`` and runs in a read-only transaction regardless of this filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MIN_QUESTION_CHARS = 3

_FLAGS = re.IGNORECASE

_INJECTION = [
    (
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|all|any|your|the)\b.{0,30}"
        r"\b(instruction|instructions|rules|prompt|prompts|guardrails?|restrictions?|guidelines|constraints)\b"
    ),
    r"\b(you are now|from now on you|pretend (to be|you)|act as (an?|the|if)|roleplay as|simulate being)\b",
    r"\b(reveal|show|print|repeat|output|leak|display)\b.{0,25}\b(system|hidden|initial|original)\b.{0,10}\b(prompt|instructions?|message)\b",
    r"\bsystem prompt\b",
    r"\b(jailbreak|dan mode|developer mode|do anything now)\b",
    r"<\|?\s*/?\s*(system|assistant|im_start|im_end)\b",
    r"\b(begin|end)\s+(of\s+)?(system|instructions?)\b",
    r"\b(disable|turn off|remove)\b.{0,20}\b(safety|guardrails?|filters?|restrictions?)\b",
]
_MUTATION = [
    r"\b(drop|truncate)\s+(table|schema|database|view|index)\b",
    r"\bdelete\s+from\b",
    r"\balter\s+(table|role|user|system)\b",
    r"\binsert\s+into\b",
    r"\bupdate\s+\S+\s+set\b",
    r"\bcreate\s+(table|role|user|extension|function|schema)\b",
    r"\bgrant\s+\w+\s+on\b",
    r"\bcopy\s+\S+\s+(to|from)\s+(program|'|stdout)",
]

_INJECTION_RE = [re.compile(p, _FLAGS | re.DOTALL) for p in _INJECTION]
_MUTATION_RE = [re.compile(p, _FLAGS) for p in _MUTATION]

MUTATION_MESSAGE = "Only read-only questions are supported: I can look data up but not change it."
TOO_SHORT_MESSAGE = "Please ask a more specific question about the data."


@dataclass(frozen=True)
class Screening:
    blocked: bool
    reason: Literal["too_short", "injection", "mutation"] | None = None
    message: str = ""


def screen(question: str) -> Screening:
    """Hygiene, then injection phrasing, then requests to change data."""
    text = (question or "").strip()
    if len(text) < MIN_QUESTION_CHARS or not any(ch.isalnum() for ch in text):
        return Screening(True, "too_short", TOO_SHORT_MESSAGE)
    # Look at the text without markup tricks (zero-width characters, repeated spaces).
    plain = re.sub("[\u200b-\u200f\u2060\ufeff]", "", text)
    plain = re.sub(r"\s+", " ", plain)
    if any(p.search(plain) for p in _INJECTION_RE):
        return Screening(True, "injection")
    if any(p.search(plain) for p in _MUTATION_RE):
        return Screening(True, "mutation", MUTATION_MESSAGE)
    return Screening(False)
