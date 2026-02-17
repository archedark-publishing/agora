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


async def test_register_search_detail_update_delete_lifecycle(client) -> None:
    payload = build_payload("Lifecycle Agent", "https://lifecycle.example.com/a2a", "weather")

    register = await client.post(
        "/api/v1/agents",
        json=payload,
        headers={"X-API-Key": "lifecycle-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    search = await client.get("/api/v1/agents", params={"skill": "weather"})
    assert search.status_code == 200
    assert any(agent["id"] == agent_id for agent in search.json()["agents"])

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == agent_id

    updated = build_payload("Lifecycle Agent Updated", "https://lifecycle.example.com/a2a", "weather")
    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=updated,
        headers={"X-API-Key": "lifecycle-key"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Lifecycle Agent Updated"

    immutable_fail = build_payload(
        "Lifecycle Agent Updated",
        "https://lifecycle.example.com/changed-path",
        "weather",
    )
    immutable_update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=immutable_fail,
        headers={"X-API-Key": "lifecycle-key"},
    )
    assert immutable_update.status_code == 400

    delete = await client.delete(
        f"/api/v1/agents/{agent_id}",
        headers={"X-API-Key": "lifecycle-key"},
    )
    assert delete.status_code == 204

    post_delete_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert post_delete_detail.status_code == 404
