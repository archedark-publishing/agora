from __future__ import annotations


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
