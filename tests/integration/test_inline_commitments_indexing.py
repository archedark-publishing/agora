from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx

from agora.database import AsyncSessionLocal
from agora.health_checker import _check_single_agent
from agora.models import Agent


@asynccontextmanager
async def _noop_pin_hostname_resolution(_hostname: str, _pinned_ip: str):
    yield


def payload(
    name: str,
    url: str,
    *,
    commitments_url: str | None = None,
) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "weather skill"}],
    }
    if commitments_url is not None:
        body["commitments_url"] = commitments_url
    return body


async def test_inline_commitments_are_indexed_and_exposed_via_api(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Inline Commitments Agent",
            "https://example.com/inline-commitments-agent",
            commitments_url="https://example.com/.well-known/agent-commitments.json",
        ),
        headers={"X-API-Key": "inline-commitments-key"},
    )
    assert register.status_code == 201
    agent_id = UUID(register.json()["id"])

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(
                200,
                json={
                    "protocolVersion": "0.3.0",
                    "name": "Inline Commitments Agent",
                    "description": "Agent with inline commitments",
                    "url": "https://example.com/inline-commitments-agent",
                    "version": "1.0.0",
                    "skills": [{"id": "weather", "name": "weather skill"}],
                },
                request=request,
            )
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Inline Commitments Agent",
                    "url": "https://example.com/inline-commitments-agent",
                    "protocolVersion": "1.4.0",
                    "skills": [{"id": "weather", "name": "weather skill"}],
                    "commitments": {
                        "summary": "Commits to secure-by-default operation",
                        "commitments": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.health_checker.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr(
        "agora.agent_json.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.health_checker.pin_hostname_resolution", _noop_pin_hostname_resolution)
    monkeypatch.setattr("agora.agent_json.pin_hostname_resolution", _noop_pin_hostname_resolution)

    now_utc = datetime.now(tz=timezone.utc)
    async with AsyncSessionLocal() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None

        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as checker_client:
            healthy = await _check_single_agent(
                agent,
                checker_client,
                now_utc,
                allow_private_network_targets=False,
            )

        assert healthy is True
        await session.commit()

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["commitments_url"] == "https://example.com/.well-known/agent-commitments.json"
    assert detail.json()["commitments_count"] == 3
    assert detail.json()["commitments_summary"] == "Commits to secure-by-default operation"

    listed = await client.get("/api/v1/agents")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["agents"][0]["commitments_url"] == "https://example.com/.well-known/agent-commitments.json"
    assert listed.json()["agents"][0]["commitments_count"] == 3
    assert listed.json()["agents"][0]["commitments_summary"] == "Commits to secure-by-default operation"
