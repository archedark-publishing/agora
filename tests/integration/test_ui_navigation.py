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


async def test_homepage_agent_card_link_loads_detail_page(client) -> None:
    payload = build_payload("Homepage Agent", "https://example.com/homepage-agent", "weather")
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

    detail = await client.get(f"/agent/{agent_id}")
    assert detail.status_code == 200
    assert "Homepage Agent" in detail.text
