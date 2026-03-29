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


async def test_well_known_agent_json_prefers_forwarded_public_url(client) -> None:
    response = await client.get(
        "/.well-known/agent.json",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "staging.the-agora.dev",
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["url"] == "https://staging.the-agora.dev"
    assert payload["contact"]["url"] == "https://staging.the-agora.dev/api/v1/agents"


async def test_well_known_did_json_is_available(client) -> None:
    response = await client.get("/.well-known/did.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/did+json")

    payload = response.json()
    # Base context always present
    assert "https://www.w3.org/ns/did/v1" in payload["@context"]
    assert payload["id"] == "did:web:the-agora.dev"
    assert payload["service"] == [
        {
            "id": "did:web:the-agora.dev#registry",
            "type": "AgentRegistry",
            "serviceEndpoint": "https://the-agora.dev",
        }
    ]
    # @context is the first key
    assert list(payload.keys())[0] == "@context"


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


async def test_register_agent_promotes_identity_did_from_agent_card_url(client, monkeypatch) -> None:
    fetched_card = {
        "protocolVersion": "0.3.0",
        "name": "Identity DID Agent",
        "description": "Fetched agent description",
        "url": "https://identity.example/agents/fetched",
        "version": "1.0.0",
        "skills": [{"id": "echo", "name": "Echo"}],
        "identity": {"did": "did:web:identity.example"},
    }

    async def _fake_fetch(url: str) -> dict[str, object]:
        assert url == "https://identity.example"
        return fetched_card

    monkeypatch.setattr(main_module, "_fetch_agent_card_from_url", _fake_fetch)

    register = await client.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={"agent_card_url": "https://identity.example"},
    )

    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")

    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:identity.example"


async def test_register_agent_prefers_top_level_did_over_identity_did(client, monkeypatch) -> None:
    fetched_card = {
        "protocolVersion": "0.3.0",
        "name": "Top-level DID Agent",
        "description": "Fetched agent description",
        "url": "https://top-level.example/agents/fetched",
        "version": "1.0.0",
        "skills": [{"id": "echo", "name": "Echo"}],
        "did": "did:web:top-level.example",
        "identity": {"did": "did:web:identity.example"},
    }

    async def _fake_fetch(url: str) -> dict[str, object]:
        assert url == "https://top-level.example"
        return fetched_card

    monkeypatch.setattr(main_module, "_fetch_agent_card_from_url", _fake_fetch)

    register = await client.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={"agent_card_url": "https://top-level.example"},
    )

    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")

    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:top-level.example"
