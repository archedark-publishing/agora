from __future__ import annotations

from hashlib import sha256
import socket

from sqlalchemy import select

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.metrics import BoundedRequestMetrics
from agora.models import Agent


def payload(name: str, url: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "security", "name": "Security"}],
    }


async def test_registration_rate_limit_blocks_rotating_api_keys(client, monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "registration_rate_limit_per_ip", 3)
    monkeypatch.setattr(main_module.settings, "registration_rate_limit_per_api_key", 100)
    monkeypatch.setattr(main_module.settings, "registration_rate_limit_global", 100)

    statuses: list[int] = []
    for idx in range(1, 5):
        response = await client.post(
            "/api/v1/agents",
            json=payload(f"agent-{idx}", f"https://example.com/rl/{idx}"),
            headers={"X-API-Key": f"rotating-key-{idx}"},
        )
        statuses.append(response.status_code)

    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429


async def test_metrics_endpoint_requires_admin_token_and_hides_raw_paths(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module.settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(main_module, "request_metrics", BoundedRequestMetrics(max_entries=4))

    missing = await client.get("/api/v1/metrics")
    assert missing.status_code == 401

    for idx in range(20):
        await client.get(f"/random-{idx}")

    register = await client.post(
        "/api/v1/agents",
        json=payload("metrics-agent", "https://example.com/metrics/agent"),
        headers={"X-API-Key": "metrics-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200

    metrics = await client.get(
        "/api/v1/metrics",
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert metrics.status_code == 200
    entries = metrics.json()["request_metrics"]
    assert len(entries) <= 4
    assert any(key.startswith("GET _unmatched 404") for key in entries)
    assert all("/random-" not in key for key in entries)
    assert any("GET /api/v1/agents/{agent_id} 200" in key for key in entries)
    assert all(agent_id not in key for key in entries)


async def test_registration_rejects_userinfo_urls(client) -> None:
    response = await client.post(
        "/api/v1/agents",
        json=payload(
            "userinfo-agent",
            "https://trusted.example.com@attacker.example.net/a2a",
        ),
        headers={"X-API-Key": "userinfo-key"},
    )
    assert response.status_code == 400
    message = str(response.json())
    assert "userinfo" in message.lower()


async def test_registration_rejects_unresolvable_hostnames(client, monkeypatch) -> None:
    def _raise(_hostname: str):
        raise socket.gaierror("unresolvable")

    monkeypatch.setattr(
        "agora.url_safety._resolve_ips",
        _raise,
    )
    response = await client.post(
        "/api/v1/agents",
        json=payload(
            "unresolved-agent",
            "https://nonexistent-subdomain-xyz-12345.invalid/a2a",
        ),
        headers={"X-API-Key": "dns-key"},
    )
    assert response.status_code == 400
    message = str(response.json())
    assert "resolve" in message.lower()


async def test_legacy_owner_hash_is_upgraded_on_successful_auth(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("legacy-owner", "https://example.com/legacy/owner"),
        headers={"X-API-Key": "legacy-owner-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]
    legacy_hash = sha256("legacy-owner-key".encode("utf-8")).hexdigest()

    async with AsyncSessionLocal() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == agent_id))
        assert agent is not None
        agent.owner_key_hash = legacy_hash
        await session.commit()

    updated = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload("legacy-owner-updated", "https://example.com/legacy/owner"),
        headers={"X-API-Key": "legacy-owner-key"},
    )
    assert updated.status_code == 200

    async with AsyncSessionLocal() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == agent_id))
        assert agent is not None
        assert agent.owner_key_hash != legacy_hash
        assert str(agent.owner_key_hash).startswith("$argon2id$")
