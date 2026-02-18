from __future__ import annotations


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
    assert "No agents registered yet" not in response.text


async def test_search_page_accepts_stale_health_filter_from_ui(client) -> None:
    response = await client.get("/search", params={"health": "stale"})
    assert response.status_code == 200
