"""Registry snapshot generation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agora.models import Agent
from agora.stale import compute_agent_stale_metadata


async def build_registry_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Build a full registry export snapshot from current DB state."""

    generated_at = datetime.now(tz=timezone.utc)
    async with session_factory() as session:
        agents = list((await session.scalars(select(Agent).order_by(Agent.registered_at.desc()))).all())

    rows: list[dict[str, Any]] = []
    for agent in agents:
        is_stale, stale_days = compute_agent_stale_metadata(agent, now=generated_at)
        rows.append(
            {
                "id": str(agent.id),
                "agent_card": agent.agent_card,
                "health_status": agent.health_status,
                "last_health_check": (
                    agent.last_health_check.isoformat() if agent.last_health_check else None
                ),
                "last_healthy_at": agent.last_healthy_at.isoformat() if agent.last_healthy_at else None,
                "registered_at": agent.registered_at.isoformat(),
                "updated_at": agent.updated_at.isoformat(),
                "is_stale": is_stale,
                "stale_days": stale_days,
            }
        )

    return {
        "generated_at": generated_at.isoformat(),
        "agents_count": len(rows),
        "agents": rows,
    }
