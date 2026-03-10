from __future__ import annotations


def payload(
    name: str,
    url: str,
    *,
    protocol_version: str | None = None,
) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "weather skill"}],
    }
    if protocol_version is not None:
        body["protocol_version"] = protocol_version
    return body


async def test_register_update_and_self_view_protocol_version(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Protocol Agent",
            "https://example.com/protocol-agent",
            protocol_version="1.0.0-rc",
        ),
        headers={"X-API-Key": "protocol-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["protocol_version"] == "1.0.0-rc"

    me = await client.get("/api/v1/me", headers={"X-API-Key": "protocol-key"})
    assert me.status_code == 200
    assert me.json()["id"] == agent_id
    assert me.json()["protocol_version"] == "1.0.0-rc"

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Protocol Agent",
            "https://example.com/protocol-agent",
            protocol_version="1.0",
        ),
        headers={"X-API-Key": "protocol-key"},
    )
    assert update.status_code == 200

    updated_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert updated_detail.status_code == 200
    assert updated_detail.json()["protocol_version"] == "1.0"

    cleared = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Protocol Agent",
            "https://example.com/protocol-agent",
            protocol_version="   ",
        ),
        headers={"X-API-Key": "protocol-key"},
    )
    assert cleared.status_code == 200

    cleared_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert cleared_detail.status_code == 200
    assert cleared_detail.json()["protocol_version"] is None


async def test_list_agents_filters_by_protocol_version(client) -> None:
    with_protocol = await client.post(
        "/api/v1/agents",
        json=payload(
            "With Protocol",
            "https://example.com/with-protocol",
            protocol_version="1.0",
        ),
        headers={"X-API-Key": "protocol-filter-key"},
    )
    assert with_protocol.status_code == 201

    without_protocol = await client.post(
        "/api/v1/agents",
        json=payload("Without Protocol", "https://example.com/without-protocol"),
        headers={"X-API-Key": "protocol-filter-key"},
    )
    assert without_protocol.status_code == 201

    has_protocol = await client.get("/api/v1/agents", params={"has_protocol_version": "true"})
    assert has_protocol.status_code == 200
    assert has_protocol.json()["total"] == 1
    assert has_protocol.json()["agents"][0]["name"] == "With Protocol"
    assert has_protocol.json()["agents"][0]["protocol_version"] == "1.0"

    no_protocol = await client.get("/api/v1/agents", params={"has_protocol_version": "false"})
    assert no_protocol.status_code == 200
    assert no_protocol.json()["total"] == 1
    assert no_protocol.json()["agents"][0]["name"] == "Without Protocol"
    assert no_protocol.json()["agents"][0]["protocol_version"] is None

    by_value = await client.get("/api/v1/agents", params={"protocol_version": "1.0"})
    assert by_value.status_code == 200
    assert by_value.json()["total"] == 1
    assert by_value.json()["agents"][0]["name"] == "With Protocol"

    invalid_empty = await client.get("/api/v1/agents", params={"protocol_version": "   "})
    assert invalid_empty.status_code == 400
    assert invalid_empty.json()["detail"] == "protocol_version cannot be empty"
