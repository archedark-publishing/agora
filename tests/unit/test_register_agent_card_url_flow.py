from __future__ import annotations

from datetime import UTC, datetime
import ipaddress
from uuid import UUID, uuid4

import httpx
import pytest_asyncio

import agora.main as main_module
from agora.database import get_db_session
from agora.main import app
from agora.models import Agent


@pytest_asyncio.fixture
async def client_with_fake_db(monkeypatch) -> httpx.AsyncClient:
    store: dict[UUID, Agent] = {}

    class FakeSession:
        async def scalar(self, *_args, **_kwargs):
            return None

        def add(self, agent: Agent) -> None:
            now = datetime.now(UTC)
            if getattr(agent, "id", None) is None:
                agent.id = uuid4()
            if getattr(agent, "registered_at", None) is None:
                agent.registered_at = now
            if getattr(agent, "updated_at", None) is None:
                agent.updated_at = now
            if getattr(agent, "health_status", None) is None:
                agent.health_status = "unknown"
            store[agent.id] = agent

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        async def refresh(self, _agent: Agent) -> None:
            return None

        async def get(self, model: type[Agent], agent_id: UUID) -> Agent | None:
            if model is not Agent:
                return None
            return store.get(agent_id)

    async def _override_get_db_session():
        yield FakeSession()

    async def _no_rate_limit(*_args, **_kwargs) -> None:
        return None

    async def _no_commitment_verification(**_kwargs) -> bool:
        return False

    async def _no_erc8004_lookup(_url: str, econ_id: str | None) -> tuple[str | None, bool]:
        return econ_id, False

    monkeypatch.setattr(main_module, "_enforce_registration_rate_limits", _no_rate_limit)
    monkeypatch.setattr(main_module, "verify_commitments_document", _no_commitment_verification)
    monkeypatch.setattr(main_module, "_compute_erc8004_verification", _no_erc8004_lookup)
    monkeypatch.setattr(
        "agora.url_safety._resolve_ips",
        lambda _hostname: [ipaddress.ip_address("93.184.216.34")],
    )

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_db_session, None)


async def test_register_agent_supports_agent_card_url_without_top_level_url(
    client_with_fake_db,
    monkeypatch,
) -> None:
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

    response = await client_with_fake_db.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={
            "agent_card_url": "https://example.com",
            "name": "Override Name",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Override Name"
    assert payload["url"] == "https://example.com/agents/fetched"


async def test_register_agent_promotes_identity_did_from_agent_card_url_with_fake_db(
    client_with_fake_db,
    monkeypatch,
) -> None:
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

    register = await client_with_fake_db.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={"agent_card_url": "https://identity.example"},
    )

    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client_with_fake_db.get(f"/api/v1/agents/{agent_id}")

    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:identity.example"


async def test_register_agent_prefers_top_level_did_over_identity_did_with_fake_db(
    client_with_fake_db,
    monkeypatch,
) -> None:
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

    register = await client_with_fake_db.post(
        "/api/v1/agents",
        headers={"X-API-Key": "owner-key"},
        json={"agent_card_url": "https://top-level.example"},
    )

    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client_with_fake_db.get(f"/api/v1/agents/{agent_id}")

    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:top-level.example"
