from __future__ import annotations


def payload(name: str, url: str, *, econ_id: str | None = None) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "weather skill"}],
    }
    if econ_id is not None:
        body["econ_id"] = econ_id
    return body


async def test_register_and_update_econ_id(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("Econ Agent", "https://example.com/econ", econ_id="econ://agent-123"),
        headers={"X-API-Key": "econ-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["econ_id"] == "econ://agent-123"

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload("Econ Agent", "https://example.com/econ", econ_id="wallet:abc"),
        headers={"X-API-Key": "econ-key"},
    )
    assert update.status_code == 200

    updated_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert updated_detail.status_code == 200
    assert updated_detail.json()["econ_id"] == "wallet:abc"


async def test_list_agents_filters_by_econ_id(client) -> None:
    with_econ = await client.post(
        "/api/v1/agents",
        json=payload("With Econ", "https://example.com/with-econ", econ_id="did:example:alice"),
        headers={"X-API-Key": "econ-filter-key"},
    )
    assert with_econ.status_code == 201

    without_econ = await client.post(
        "/api/v1/agents",
        json=payload("Without Econ", "https://example.com/without-econ"),
        headers={"X-API-Key": "econ-filter-key"},
    )
    assert without_econ.status_code == 201

    has_econ = await client.get("/api/v1/agents", params={"has_econ_id": "true"})
    assert has_econ.status_code == 200
    assert has_econ.json()["total"] == 1
    assert has_econ.json()["agents"][0]["name"] == "With Econ"
    assert has_econ.json()["agents"][0]["econ_id"] == "did:example:alice"

    by_value = await client.get("/api/v1/agents", params={"econ_id": "did:example:alice"})
    assert by_value.status_code == 200
    assert by_value.json()["total"] == 1
    assert by_value.json()["agents"][0]["name"] == "With Econ"
