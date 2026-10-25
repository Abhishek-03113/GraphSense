"""A simple in-process rate limiter for ``/api/chat/messages`` (per client address).

Each question costs model calls and database time, so the limit is a sliding window
(``CHAT_RATE_LIMIT_PER_MIN`` requests per 60 seconds per client; ``0`` turns it off).
It only knows about this process: with several workers the real limit is higher, and
a gateway limiter in front of the service is the stronger control.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from src.config import get_settings

WINDOW_S = 60.0
MAX_TRACKED_CLIENTS = 10_000


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = WINDOW_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float | None:
        """Record a request.  ``None`` when allowed, else the seconds until a request would be."""
        if self.limit <= 0:
            return None
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(0.0, self.window_s - (now - hits[0]))
        hits.append(now)
        if len(self._hits) > MAX_TRACKED_CLIENTS:
            self._prune(now)
        return None

    def _prune(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window_s]:
            del self._hits[key]


_limiter: SlidingWindowLimiter | None = None


def get_chat_limiter() -> SlidingWindowLimiter:
    """The shared limiter, rebuilt if the configured limit changed."""
    global _limiter
    limit = get_settings().CHAT_RATE_LIMIT_PER_MIN
    if _limiter is None or _limiter.limit != limit:
        _limiter = SlidingWindowLimiter(limit)
    return _limiter


def reset_chat_limiter() -> None:
    global _limiter
    _limiter = None


def client_address(request: Request) -> str:
    """The caller's address.  ``X-Forwarded-For`` is honoured only when ``CHAT_RATE_LIMIT_TRUST_FORWARDED`` is set."""
    if get_settings().CHAT_RATE_LIMIT_TRUST_FORWARDED:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
