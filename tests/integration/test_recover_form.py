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


async def test_recover_form_renders_backend_expected_start_fields(client) -> None:
    response = await client.get("/recover")
    assert response.status_code == 200
    assert 'action="/recover/start"' in response.text
    assert 'name="agent_id"' in response.text
    assert 'name="url"' not in response.text
    assert 'action="/recover/verify"' not in response.text


async def test_recover_start_advances_to_complete_form(client) -> None:
    payload = build_payload("Recover Form Agent", "https://example.com/recover-form-agent")
    register = await client.post(
        "/api/v1/agents",
        json=payload,
        headers={"X-API-Key": "recover-form-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    response = await client.post("/recover/start", data={"agent_id": agent_id})
    assert response.status_code == 200
    assert 'action="/recover/complete"' in response.text
    assert 'name="new_api_key"' in response.text
    assert f'value="{agent_id}"' in response.text
    assert 'name="recovery_session_secret"' in response.text
