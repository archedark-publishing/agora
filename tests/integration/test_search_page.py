from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.models import Agent


def build_payload(name: str, url: str, skill_id: str = "weather") -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": skill_id, "name": f"{skill_id} skill"}],
    }


async def set_agent_health_state(
    *,
    name: str,
    health_status: str,
    registered_at: datetime,
    last_healthy_at: datetime | None,
) -> None:
    async with AsyncSessionLocal() as session:
        agent = await session.scalar(select(Agent).where(Agent.name == name))
        assert agent is not None
        agent.health_status = health_status
        agent.registered_at = registered_at
        agent.last_healthy_at = last_healthy_at
        await session.commit()


async def test_search_page_lists_registered_agents(client) -> None:
    payload = build_payload("Search Page Agent", "https://example.com/search-page-agent")
    register = await client.post(
        "/api/v1/agents",
        json=payload,
        headers={"X-API-Key": "search-page-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    response = await client.get("/search")
    assert response.status_code == 200
    assert "Search Page Agent" in response.text
    assert f'/agent/{agent_id}' in response.text
    assert "Reliability:" in response.text
    assert "Public incidents:" in response.text
    assert "No agents registered yet" not in response.text


async def test_search_page_accepts_stale_health_filter_from_ui(client) -> None:
    stale_agent = "Stale UI Agent"
    non_stale_agent = "Recent Unhealthy Agent"

    stale_register = await client.post(
        "/api/v1/agents",
        json=build_payload(stale_agent, "https://example.com/stale-ui-agent"),
        headers={"X-API-Key": "search-page-stale-key"},
    )
    assert stale_register.status_code == 201

    non_stale_register = await client.post(
        "/api/v1/agents",
        json=build_payload(non_stale_agent, "https://example.com/recent-unhealthy-agent"),
        headers={"X-API-Key": "search-page-stale-key"},
    )
    assert non_stale_register.status_code == 201

    now = datetime.now(tz=timezone.utc)
    await set_agent_health_state(
        name=stale_agent,
        health_status="unhealthy",
        registered_at=now - timedelta(days=10),
        last_healthy_at=now - timedelta(days=8),
    )
    await set_agent_health_state(
        name=non_stale_agent,
        health_status="unhealthy",
        registered_at=now - timedelta(days=1),
        last_healthy_at=now - timedelta(hours=12),
    )

    response = await client.get("/search", params={"health": "stale"})
    assert response.status_code == 200
    assert stale_agent in response.text
    assert non_stale_agent not in response.text


async def test_search_page_accepts_q_filter(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=build_payload("Ada Match Agent", "https://example.com/ada-match-agent"),
        headers={"X-API-Key": "search-page-q-key"},
    )
    assert register.status_code == 201

    response = await client.get("/search", params={"q": "Ada"})
    assert response.status_code == 200
    assert "Ada Match Agent" in response.text


async def test_search_page_accepts_healthy_filter(client) -> None:
    healthy_agent = "Healthy UI Agent"
    unknown_agent = "Unknown UI Agent"

    healthy_register = await client.post(
        "/api/v1/agents",
        json=build_payload(healthy_agent, "https://example.com/healthy-ui-agent"),
        headers={"X-API-Key": "search-page-healthy-key"},
    )
    assert healthy_register.status_code == 201

    unknown_register = await client.post(
        "/api/v1/agents",
        json=build_payload(unknown_agent, "https://example.com/unknown-ui-agent"),
        headers={"X-API-Key": "search-page-healthy-key"},
    )
    assert unknown_register.status_code == 201

    now = datetime.now(tz=timezone.utc)
    await set_agent_health_state(
        name=healthy_agent,
        health_status="healthy",
        registered_at=now - timedelta(hours=3),
        last_healthy_at=now - timedelta(hours=3),
    )
    await set_agent_health_state(
        name=unknown_agent,
        health_status="unknown",
        registered_at=now - timedelta(hours=1),
        last_healthy_at=None,
    )

    response = await client.get("/search", params={"health": "healthy"})
    assert response.status_code == 200
    assert healthy_agent in response.text
    assert unknown_agent not in response.text


async def test_search_page_accepts_skill_filter(client) -> None:
    writing_agent = "Writing Skill Agent"
    weather_agent = "Weather Skill Agent"

    writing_register = await client.post(
        "/api/v1/agents",
        json=build_payload(
            writing_agent,
            "https://example.com/writing-skill-agent",
            skill_id="writing",
        ),
        headers={"X-API-Key": "search-page-skill-key"},
    )
    assert writing_register.status_code == 201

    weather_register = await client.post(
        "/api/v1/agents",
        json=build_payload(
            weather_agent,
            "https://example.com/weather-skill-agent",
            skill_id="weather",
        ),
        headers={"X-API-Key": "search-page-skill-key"},
    )
    assert weather_register.status_code == 201

    response = await client.get("/search", params={"skill": "writing"})
    assert response.status_code == 200
    assert writing_agent in response.text
    assert weather_agent not in response.text


async def test_agents_api_accepts_all_and_stale_health_values(client) -> None:
    payload = build_payload("Health Filter Agent", "https://example.com/health-filter-agent")
    register = await client.post(
        "/api/v1/agents",
        json=payload,
        headers={"X-API-Key": "health-filter-key"},
    )
    assert register.status_code == 201

    all_response = await client.get("/api/v1/agents", params=[("health", "all")])
    assert all_response.status_code == 200

    stale_response = await client.get("/api/v1/agents", params=[("health", "stale")])
    assert stale_response.status_code == 200


async def test_search_page_shows_erc8004_badge_for_verified_agents(client, monkeypatch) -> None:
    async def _fake_discovery(
        _endpoint_url: str,
        *,
        client: httpx.AsyncClient,
        allow_private_network_targets: bool,
    ) -> str | None:
        return "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e:22"

    monkeypatch.setattr(main_module, "discover_erc8004_registration_econ_id", _fake_discovery)

    register = await client.post(
        "/api/v1/agents",
        json=build_payload("ERC Search Agent", "https://example.com/erc-search-agent"),
        headers={"X-API-Key": "erc-search-key"},
    )
    assert register.status_code == 201

    response = await client.get("/search")
    assert response.status_code == 200
    assert "ERC Search Agent" in response.text
    assert "ERC-8004" in response.text
