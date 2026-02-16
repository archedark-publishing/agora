"""In-memory sliding-window rate limiting helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic


@dataclass(slots=True)
class RateLimitResult:
    """Result of a rate-limit check."""

    allowed: bool
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """Simple in-memory sliding-window limiter keyed by arbitrary strings."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=False, retry_after_seconds=max(window_seconds, 1))

        now = monotonic()
        window_start = now - window_seconds

        with self._lock:
            bucket = self._windows.setdefault(key, deque())
            while bucket and bucket[0] <= window_start:
                bucket.popleft()

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, ceil(window_seconds - (now - oldest)))
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

            bucket.append(now)
            return RateLimitResult(allowed=True, retry_after_seconds=0)
