from __future__ import annotations

from sqlalchemy import select

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.models import Agent


async def test_well_known_agent_json_is_available(client) -> None:
    response = await client.get("/.well-known/agent.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    payload = response.json()
    assert payload["name"] == "Agent Agora"
    assert payload["description"] == "Agent registry and discovery"
    assert payload["url"] == "http://testserver"
    assert payload["capabilities"] == ["registry", "discovery"]
    assert payload["contact"]["url"] == "http://testserver/api/v1/agents"


async def test_register_agent_supports_agent_card_url(client, monkeypatch) -> None:
    fetched_card = {
        "protocolVersion": "0.3.0",
        "name": "Fetched Agent Name",
        "description": "Fetched agent description",
        "url": "https://example.com/agents/fetched",
        "version": "1.0.0",
        "skills": [{"id": "echo", "name": "Echo"}],
    }

    async def _fake_fetch(url: str) -> dict[str, object]:
        assert url == "https://example.com"
        return fetched_card

    monkeypatch.setattr(main_module, "_fetch_agent_card_from_url", _fake_fetch)

    response = await client.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={
            "agent_card_url": "https://example.com",
            "name": "Override Name",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Override Name"
    assert body["url"] == "https://example.com/agents/fetched"

    async with AsyncSessionLocal() as session:
        agent = await session.scalar(select(Agent).where(Agent.url == body["url"]))

    assert agent is not None
    assert agent.agent_card_url == "https://example.com"
    assert agent.description == "Fetched agent description"
    assert agent.name == "Override Name"
