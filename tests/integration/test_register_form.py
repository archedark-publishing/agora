from __future__ import annotations

import json


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


async def test_register_form_renders_expected_backend_field_names(client) -> None:
    response = await client.get("/register")
    assert response.status_code == 200
    assert 'name="agent_card_json"' in response.text
    assert 'name="api_key"' in response.text
    assert 'name="card_json"' not in response.text


async def test_register_form_submission_registers_agent(client) -> None:
    payload = build_payload("Form Agent", "https://example.com/form-agent", "weather")
    response = await client.post(
        "/register",
        data={
            "agent_card_json": json.dumps(payload),
            "api_key": "form-owner-key",
        },
    )
    assert response.status_code == 201
    assert "Form Agent is live!" in response.text

    search = await client.get("/api/v1/agents", params={"skill": "weather"})
    assert search.status_code == 200
    assert any(agent["name"] == "Form Agent" for agent in search.json()["agents"])
