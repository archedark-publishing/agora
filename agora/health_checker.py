"""Background health-check logic for registered agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agora.agent_json import verify_agent_json_manifest_with_indexing_metadata
from agora.commitments import verify_commitments_document
from agora.erc8004 import discover_erc8004_registration_econ_id, resolve_erc8004_verification
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


def build_agent_card_probe_url(agent_url: str, agent_card_url: str | None = None) -> str:
    """Build the primary canonical health probe URL for an agent origin."""

    return build_agent_card_probe_urls(agent_url, agent_card_url)[0]


def _candidates_for_base(base_url: str) -> list[str]:
    """Build the six ordered probe candidates for a single base URL."""
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    scheme = parts.scheme or "https"
    port = parts.port
    port_fragment = ""
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port_fragment = f":{port}"

    origin = f"{scheme}://{host}{port_fragment}"
    raw_path = parts.path or "/"
    # Trailing slash ensured so concatenation matches the urljoin semantics
    # registration uses to resolve the card location.
    path_prefix = raw_path if raw_path.endswith("/") else f"{raw_path}/"
    normalized_base_url = f"{origin}{raw_path}"

    return [
        f"{origin}/.well-known/agent-card.json",
        f"{origin}/.well-known/agent.json",
        f"{origin}{path_prefix}.well-known/agent-card.json",
        f"{origin}{path_prefix}.well-known/agent.json",
        normalized_base_url,
        f"{origin}/",
    ]


def build_agent_card_probe_urls(agent_url: str, agent_card_url: str | None = None) -> list[str]:
    """
    Build ordered health probe URLs for an agent.

    `agent_url` is the card's self-asserted endpoint (where clients go).
    `agent_card_url` is the URL the card was actually fetched from at
    registration -- the proven location. The two can differ: a card fetched at
    `https://example.com/agents/demo/.well-known/agent.json` may declare
    `"url": "https://example.com/rpc"`. Probing only the endpoint would miss
    the proven card location and strand the listing pending forever, so the
    proven-location candidates come first.

    When `agent_card_url` is given and differs from `agent_url`, the endpoint
    candidates are appended after the proven-location candidates (the endpoint
    is still where clients go, so it stays a reasonable secondary target).
    When the two are identical (or no card URL is given), the result is exactly
    the single-base list -- no behavior change for the common case.

    Probe order per base:
    1. `/.well-known/agent-card.json` on the base origin (primary contract target)
    2. `/.well-known/agent.json` on the base origin (registration fetch location;
       kept in the same list so registration and health checks agree on where a
       card may live)
    3. `/.well-known/agent-card.json` under the base URL's own path
    4. `/.well-known/agent.json` under the base URL's own path
    5. The base URL itself (query/fragment removed)
    6. Root `/` on the base origin

    Entries 3-4 exist because registration resolves the card path-relative to
    `agent_card_url` (`urljoin(f"{base}/", ".well-known/agent.json")`). A card
    served only under a path would pass registration validation but fail every
    health check if the probes only covered origin-root locations, stranding the
    listing pending forever. Probing the same path-relative locations keeps one
    canonical list shared by the registration preflight, the retry endpoint,
    and the background checker.
    """

    primary_base = agent_card_url or agent_url
    candidates = _candidates_for_base(primary_base)
    if agent_card_url and agent_card_url.rstrip("/") != agent_url.rstrip("/"):
        candidates += _candidates_for_base(agent_url)

    # Preserve order while removing duplicates (for example when the agent URL
    # path is "/" the path-relative entries duplicate the origin-level ones,
    # and when both bases are equivalent the second list collapses entirely).
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


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

    probe_urls = build_agent_card_probe_urls(agent.url, agent.agent_card_url)
    previous_last_healthy = agent.last_healthy_at
    is_healthy = False
    discovered_protocol_version: str | None = None

    for probe_url in probe_urls:
        try:
            safe_target = assert_url_safe_for_outbound(
                probe_url,
                allow_private=allow_private_network_targets,
            )
            async with pin_hostname_resolution(safe_target.hostname, safe_target.pinned_ip):
                response = await client.get(probe_url, follow_redirects=False)
            response.raise_for_status()
            payload = response.json()
            validated_card = validate_agent_card(payload)
            discovered_protocol_version = validated_card.card.protocol_version
            is_healthy = True
            break
        except (httpx.HTTPError, ValueError, AgentCardValidationError, URLSafetyError):
            continue

    if is_healthy:
        agent.health_status = "healthy"
        agent.last_health_check = now_utc
        agent.last_healthy_at = now_utc
        agent.protocol_version = discovered_protocol_version
    elif previous_last_healthy is not None:
        # Regression: this endpoint was verified healthy before and has now
        # gone down.
        agent.health_status = "unhealthy"
        agent.last_health_check = now_utc
        agent.last_healthy_at = previous_last_healthy
        agent.protocol_version = None
    else:
        # Never passed proof-of-life (e.g. a minimal email-verified listing
        # with an informational URL): there is no verified state to regress
        # from, so it stays "unknown" rather than "unhealthy".
        agent.health_status = "unknown"
        agent.last_health_check = now_utc
        agent.last_healthy_at = None
        agent.protocol_version = None

    discovered_econ_id = await discover_erc8004_registration_econ_id(
        agent.url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    verification = resolve_erc8004_verification(agent.econ_id, discovered_econ_id)
    agent.econ_id = verification.econ_id
    agent.erc8004_verified = verification.verified

    agent.commitment_verified = await verify_commitments_document(
        commitments_url=agent.commitments_url,
        did=agent.did,
        did_verified=agent.did_verified,
        allow_private_network_targets=allow_private_network_targets,
        client=client,
    )

    (
        agent.agent_json_verified,
        agent.oatr_issuer_id,
        agent.commitments_count,
        agent.commitments_summary,
    ) = await verify_agent_json_manifest_with_indexing_metadata(
        agent_url=agent.url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )

    return is_healthy


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
                if not agent.url:
                    # Email-only directory listings have no endpoint to probe;
                    # liveness comes from heartbeats instead.
                    summary.skipped_count += 1
                    continue
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
