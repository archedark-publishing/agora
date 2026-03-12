from __future__ import annotations

import httpx

import agora.main as main_module


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
    response = await client.get("/search", params={"health": "stale"})
    assert response.status_code == 200


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
    response = await client.get("/search", params={"health": "healthy"})
    assert response.status_code == 200


async def test_search_page_accepts_skill_filter(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=build_payload(
            "Writing Skill Agent",
            "https://example.com/writing-skill-agent",
            skill_id="writing",
        ),
        headers={"X-API-Key": "search-page-skill-key"},
    )
    assert register.status_code == 201

    response = await client.get("/search", params={"skill": "writing"})
    assert response.status_code == 200
    assert "Writing Skill Agent" in response.text


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
