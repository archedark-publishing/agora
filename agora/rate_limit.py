"""Sliding-window rate limiting helpers with optional shared Redis backend."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
from math import ceil
from secrets import token_hex
from threading import Lock
from time import monotonic
from typing import Protocol

try:  # pragma: no cover - import guard
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - dependency/runtime guard
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        """Fallback redis exception type when dependency is unavailable."""


@dataclass(slots=True)
class RateLimitResult:
    """Result of a rate-limit check."""

    allowed: bool
    retry_after_seconds: int


class RateLimitBackendError(RuntimeError):
    """Raised when the configured rate-limit backend is unavailable."""


class RateLimiter(Protocol):
    """Protocol implemented by all limiter backends."""

    async def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check and record a request in the selected window."""

    async def close(self) -> None:
        """Release backend resources if needed."""

    async def reset(self) -> None:
        """Clear limiter state (primarily for test isolation)."""


class SlidingWindowRateLimiter:
    """Simple in-memory sliding-window limiter keyed by arbitrary strings."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = Lock()

    async def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
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

    async def close(self) -> None:
        return

    async def reset(self) -> None:
        with self._lock:
            self._windows.clear()


class RedisSlidingWindowRateLimiter:
    """Redis-backed sliding-window limiter shared across app instances."""

    _SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local window_start = now_ms - window_ms

redis.call("ZREMRANGEBYSCORE", key, 0, window_start)
local count = redis.call("ZCARD", key)
if count >= limit then
  local oldest = redis.call("ZRANGE", key, 0, 0, "WITHSCORES")
  local oldest_ms = tonumber(oldest[2]) or now_ms
  local retry_ms = window_ms - (now_ms - oldest_ms)
  if retry_ms < 1 then
    retry_ms = 1
  end
  redis.call("PEXPIRE", key, window_ms + 1000)
  return {0, retry_ms}
end

redis.call("ZADD", key, now_ms, member)
redis.call("PEXPIRE", key, window_ms + 1000)
return {1, 0}
"""

    def __init__(self, *, redis_url: str, prefix: str = "agora:rate_limit") -> None:
        if Redis is None:
            raise RuntimeError(
                "redis package is not installed but RATE_LIMIT_BACKEND is set to redis"
            )
        self._client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        self._prefix = prefix

    def _redis_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def check(self, *, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=False, retry_after_seconds=max(window_seconds, 1))

        now_ms = int(monotonic() * 1000)
        window_ms = window_seconds * 1000
        member = f"{now_ms}:{token_hex(8)}"

        try:
            result = await self._client.eval(
                self._SLIDING_WINDOW_SCRIPT,
                1,
                self._redis_key(key),
                now_ms,
                window_ms,
                limit,
                member,
            )
        except RedisError as exc:  # pragma: no cover - backend failure path
            raise RateLimitBackendError("Rate-limit backend unavailable") from exc

        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise RateLimitBackendError("Rate-limit backend returned unexpected response")

        allowed_raw, retry_ms_raw = result
        allowed = bool(int(allowed_raw))
        retry_ms = int(retry_ms_raw)
        retry_after = max(1, ceil(retry_ms / 1000)) if not allowed else 0
        return RateLimitResult(allowed=allowed, retry_after_seconds=retry_after)

    async def close(self) -> None:
        await self._client.aclose()

    async def reset(self) -> None:
        keys: list[str] = []
        try:
            async for key in self._client.scan_iter(match=f"{self._prefix}:*"):
                keys.append(str(key))
        except RedisError as exc:  # pragma: no cover - backend failure path
            raise RateLimitBackendError("Rate-limit backend unavailable") from exc
        if keys:
            await self._client.delete(*keys)


def create_rate_limiter(
    *,
    backend: str,
    redis_url: str | None,
    prefix: str = "agora:rate_limit",
    logger: logging.Logger | None = None,
) -> tuple[RateLimiter, bool]:
    """Create a configured rate limiter and indicate if it uses shared state."""

    normalized_backend = backend.strip().lower()
    if normalized_backend == "memory":
        return SlidingWindowRateLimiter(), False

    if normalized_backend == "redis":
        if not redis_url:
            raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        return RedisSlidingWindowRateLimiter(redis_url=redis_url, prefix=prefix), True

    if normalized_backend == "auto":
        if redis_url:
            return RedisSlidingWindowRateLimiter(redis_url=redis_url, prefix=prefix), True
        if logger:
            logger.warning(
                "rate_limit_backend_auto_fallback backend=memory reason=redis_url_missing"
            )
        return SlidingWindowRateLimiter(), False

    raise ValueError(f"Unsupported RATE_LIMIT_BACKEND value: {backend}")
