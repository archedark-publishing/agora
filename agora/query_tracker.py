"""Track recently queried agents for selective background health checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import UUID


class QueryTracker:
    """In-memory tracker for per-agent last query timestamps."""

    def __init__(self) -> None:
        self._last_queried: dict[UUID, datetime] = {}
        self._lock = Lock()

    def mark(self, agent_id: UUID, at: datetime | None = None) -> None:
        timestamp = at or datetime.now(tz=timezone.utc)
        with self._lock:
            self._last_queried[agent_id] = timestamp

    def recent_agent_ids(self, within: timedelta, now: datetime | None = None) -> list[UUID]:
        current = now or datetime.now(tz=timezone.utc)
        cutoff = current - within
        with self._lock:
            # Opportunistically prune stale entries while selecting active ones.
            to_remove = [agent_id for agent_id, ts in self._last_queried.items() if ts < cutoff]
            for agent_id in to_remove:
                self._last_queried.pop(agent_id, None)
            return [agent_id for agent_id, ts in self._last_queried.items() if ts >= cutoff]
