from __future__ import annotations

async def test_register_page_renders_agent_handoff_builder(client) -> None:
    response = await client.get("/register")
    assert response.status_code == 200
    assert "Give this to your Agent and it will handle the rest." in response.text
    assert 'id="agent_handoff_prompt"' in response.text
    assert 'id="agent-card-url"' in response.text
    assert "Copy" in response.text
    assert "/api/v1/agents" in response.text
    assert "X-API-Key" in response.text
    assert 'name="owner_api_key"' not in response.text
    assert 'name="skill_md_url"' not in response.text
    assert 'name="agent_url"' not in response.text
    assert 'name="agent_card_json"' not in response.text
    assert 'name="api_key"' not in response.text


async def test_register_page_no_longer_accepts_manual_post_submission(client) -> None:
    response = await client.post(
        "/register",
        data={
            "agent_card_json": "{}",
            "api_key": "form-owner-key",
        },
    )
    assert response.status_code == 405
