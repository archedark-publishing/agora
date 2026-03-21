from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import update

from agora.database import AsyncSessionLocal
from agora.models import Agent


def build_payload(
    name: str,
    url: str,
    skill_id: str = "weather",
    *,
    protocol_version: str | None = None,
) -> dict:
    payload = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": skill_id, "name": f"{skill_id} skill"}],
    }
    if protocol_version is not None:
        payload["protocol_version"] = protocol_version
    return payload


def _extract_health_rate_percent(page_html: str) -> int:
    match = re.search(
        r'<div class="stat-value">\s*(\d+)%\s*</div>\s*<div class="stat-label">Health rate</div>',
        page_html,
    )
    assert match is not None
    return int(match.group(1))


async def _set_agent_health_status(agent_id: str, status: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Agent)
            .where(Agent.id == UUID(agent_id))
            .values(health_status=status)
        )
        await session.commit()


async def test_homepage_agent_card_link_loads_detail_page(client) -> None:
    payload = build_payload(
        "Homepage Agent",
        "https://example.com/homepage-agent",
        "weather",
        protocol_version="1.0.0",
    )
    register = await client.post(
        "/api/v1/agents",
        json=payload,
        headers={"X-API-Key": "homepage-agent-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    home = await client.get("/")
    assert home.status_code == 200
    assert f'/agent/{agent_id}' in home.text
    assert 'href="https://github.com/archedark-publishing/agora"' in home.text
    assert "A2A 1.0.0" in home.text

    detail = await client.get(f"/agent/{agent_id}")
    assert detail.status_code == 200
    assert "Homepage Agent" in detail.text
    assert "Reputation" in detail.text
    assert 'href="#reputation"' in detail.text
    assert "Incident reporting is API-only" in detail.text
    assert "POST /api/v1/agents/{id}/incidents" in detail.text
    assert "Submit incident report (authenticated)" not in detail.text


async def test_homepage_health_rate_is_zero_when_no_agents(client) -> None:
    home = await client.get("/")
    assert home.status_code == 200
    assert _extract_health_rate_percent(home.text) == 0


async def test_homepage_health_rate_is_100_when_all_agents_healthy(client) -> None:
    agent_ids: list[str] = []
    for i in range(2):
        payload = build_payload(
            f"Healthy Agent {i + 1}",
            f"https://example.com/healthy-{i + 1}",
            "weather",
        )
        register = await client.post(
            "/api/v1/agents",
            json=payload,
            headers={"X-API-Key": f"healthy-agent-key-{i + 1}"},
        )
        assert register.status_code == 201
        agent_ids.append(register.json()["id"])

    for agent_id in agent_ids:
        await _set_agent_health_status(agent_id, "healthy")

    home = await client.get("/")
    assert home.status_code == 200
    assert _extract_health_rate_percent(home.text) == 100


async def test_homepage_health_rate_rounds_to_nearest_integer(client) -> None:
    agent_ids: list[str] = []
    for i in range(3):
        payload = build_payload(
            f"Rounding Agent {i + 1}",
            f"https://example.com/rounding-{i + 1}",
            "weather",
        )
        register = await client.post(
            "/api/v1/agents",
            json=payload,
            headers={"X-API-Key": f"rounding-agent-key-{i + 1}"},
        )
        assert register.status_code == 201
        agent_ids.append(register.json()["id"])

    await _set_agent_health_status(agent_ids[0], "healthy")
    await _set_agent_health_status(agent_ids[1], "healthy")
    await _set_agent_health_status(agent_ids[2], "unhealthy")

    home = await client.get("/")
    assert home.status_code == 200
    assert _extract_health_rate_percent(home.text) == 67
