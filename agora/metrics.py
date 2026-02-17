"""Bounded in-memory request metrics helpers."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock


class BoundedRequestMetrics:
    """Track request counters with bounded cardinality and LRU eviction."""

    def __init__(self, *, max_entries: int = 2048) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._metrics: OrderedDict[str, int] = OrderedDict()
        self._lock = Lock()

    def increment(self, key: str) -> None:
        with self._lock:
            current = self._metrics.get(key)
            if current is not None:
                self._metrics[key] = current + 1
                self._metrics.move_to_end(key)
                return

            if len(self._metrics) >= self._max_entries:
                self._metrics.popitem(last=False)
            self._metrics[key] = 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._metrics)

    def clear(self) -> None:
        with self._lock:
            self._metrics.clear()
