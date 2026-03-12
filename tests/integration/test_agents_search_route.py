from __future__ import annotations


def payload(name: str, url: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "Weather"}],
    }


async def test_agents_search_route_resolves_before_agent_id_route(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("Search Route Agent", "https://example.com/search-route-agent"),
        headers={"X-API-Key": "search-route-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    search = await client.get("/api/v1/agents/search", params={"q": "Search Route"})
    assert search.status_code == 200
    body = search.json()
    assert body["total"] == 1
    assert body["agents"][0]["id"] == agent_id

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == agent_id

    invalid_uuid = await client.get("/api/v1/agents/not-a-uuid")
    assert invalid_uuid.status_code == 422
