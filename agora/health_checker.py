"""Background health-check logic for registered agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agora.models import Agent
from agora.query_tracker import QueryTracker
from agora.url_safety import (
    URLSafetyError,
    assert_url_safe_for_outbound,
    pin_hostname_resolution,
)
from agora.validation import AgentCardValidationError, validate_agent_card


@dataclass(slots=True)
class HealthCheckSummary:
    """Summary metrics for a single health-check cycle."""

    checked_count: int = 0
    healthy_count: int = 0
    unhealthy_count: int = 0
    skipped_count: int = 0


def build_agent_card_probe_url(agent_url: str) -> str:
    """Build the canonical health probe URL for an agent origin."""

    parts = urlsplit(agent_url)
    host = parts.hostname or ""
    scheme = parts.scheme or "https"
    port = parts.port
    port_fragment = ""
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port_fragment = f":{port}"
    return f"{scheme}://{host}{port_fragment}/.well-known/agent-card.json"


async def _check_single_agent(
    agent: Agent,
    client: httpx.AsyncClient,
    now_utc: datetime,
    *,
    allow_private_network_targets: bool,
) -> bool:
    """
    Check a single agent and persist health fields.

    Returns:
        bool: True when healthy, False when unhealthy.
    """

    probe_url = build_agent_card_probe_url(agent.url)
    previous_last_healthy = agent.last_healthy_at
    try:
        safe_target = assert_url_safe_for_outbound(
            probe_url,
            allow_private=allow_private_network_targets,
        )
        async with pin_hostname_resolution(safe_target.hostname, safe_target.pinned_ip):
            response = await client.get(probe_url, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        validate_agent_card(payload)
    except (httpx.HTTPError, ValueError, AgentCardValidationError, URLSafetyError):
        agent.health_status = "unhealthy"
        agent.last_health_check = now_utc
        agent.last_healthy_at = previous_last_healthy
        return False

    agent.health_status = "healthy"
    agent.last_health_check = now_utc
    agent.last_healthy_at = now_utc
    return True


async def run_health_check_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    query_tracker: QueryTracker,
    *,
    timeout_seconds: int = 10,
    allow_private_network_targets: bool = False,
) -> HealthCheckSummary:
    """Run one selective health-check cycle over recently queried agents."""

    summary = HealthCheckSummary()
    now_utc = datetime.now(tz=timezone.utc)
    candidate_ids = query_tracker.recent_agent_ids(within=timedelta(hours=24), now=now_utc)
    if not candidate_ids:
        return summary

    timeout = httpx.Timeout(timeout_seconds)
    async with session_factory() as session:
        agents = list((await session.scalars(select(Agent).where(Agent.id.in_(candidate_ids)))).all())
        if not agents:
            return summary

        async with httpx.AsyncClient(timeout=timeout) as client:
            for agent in agents:
                summary.checked_count += 1
                healthy = await _check_single_agent(
                    agent,
                    client,
                    now_utc,
                    allow_private_network_targets=allow_private_network_targets,
                )
                if healthy:
                    summary.healthy_count += 1
                else:
                    summary.unhealthy_count += 1

        missing_count = len(candidate_ids) - len(agents)
        if missing_count > 0:
            summary.skipped_count += missing_count

        # MVP policy: stale agents are advisory only; no auto-removal occurs here.
        await session.commit()
    return summary
