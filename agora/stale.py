"""Shared stale-computation helpers for API/UI/export serializers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_

from agora.models import Agent

STALE_THRESHOLD_DAYS = 7


def compute_stale_metadata(
    *,
    health_status: str,
    last_healthy_at: datetime | None,
    registered_at: datetime,
    now: datetime | None = None,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> tuple[bool, int]:
    """Compute stale fields according to MVP interview decisions."""

    if health_status != "unhealthy":
        return False, 0

    reference = last_healthy_at or registered_at
    now_utc = now or datetime.now(tz=timezone.utc)
    elapsed = now_utc - reference
    is_stale = elapsed > timedelta(days=threshold_days)
    return is_stale, elapsed.days if is_stale else 0


def compute_agent_stale_metadata(
    agent: Agent,
    *,
    now: datetime | None = None,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> tuple[bool, int]:
    """Convenience wrapper for model instances."""

    return compute_stale_metadata(
        health_status=agent.health_status,
        last_healthy_at=agent.last_healthy_at,
        registered_at=agent.registered_at,
        now=now,
        threshold_days=threshold_days,
    )


def stale_filter_expression(
    now: datetime,
    *,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> Any:
    """SQLAlchemy expression implementing stale=true semantics."""

    stale_cutoff = now - timedelta(days=threshold_days)
    return and_(
        Agent.health_status == "unhealthy",
        or_(
            and_(Agent.last_healthy_at.is_not(None), Agent.last_healthy_at < stale_cutoff),
            and_(Agent.last_healthy_at.is_(None), Agent.registered_at < stale_cutoff),
        ),
    )
