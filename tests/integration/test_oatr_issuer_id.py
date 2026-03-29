from __future__ import annotations


def payload(
    name: str,
    url: str,
    *,
    oatr_issuer_id: str | None = None,
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
    if oatr_issuer_id is not None:
        body["identity"] = {"oatr_issuer_id": oatr_issuer_id}
    return body


async def test_register_and_update_oatr_issuer_id(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "OATR Agent",
            "https://example.com/oatr-agent",
            oatr_issuer_id="issuer-alpha",
        ),
        headers={"X-API-Key": "oatr-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["oatr_issuer_id"] == "issuer-alpha"

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "OATR Agent",
            "https://example.com/oatr-agent",
            oatr_issuer_id="issuer-beta",
        ),
        headers={"X-API-Key": "oatr-key"},
    )
    assert update.status_code == 200

    updated_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert updated_detail.status_code == 200
    assert updated_detail.json()["oatr_issuer_id"] == "issuer-beta"


async def test_list_agents_filters_by_oatr_issuer_id(client) -> None:
    with_issuer = await client.post(
        "/api/v1/agents",
        json=payload(
            "With OATR",
            "https://example.com/with-oatr",
            oatr_issuer_id="issuer-123",
        ),
        headers={"X-API-Key": "oatr-filter-key"},
    )
    assert with_issuer.status_code == 201

    without_issuer = await client.post(
        "/api/v1/agents",
        json=payload("Without OATR", "https://example.com/without-oatr"),
        headers={"X-API-Key": "oatr-filter-key"},
    )
    assert without_issuer.status_code == 201

    by_issuer = await client.get("/api/v1/agents", params={"oatr_issuer_id": "issuer-123"})
    assert by_issuer.status_code == 200
    assert by_issuer.json()["total"] == 1
    assert by_issuer.json()["agents"][0]["name"] == "With OATR"
    assert by_issuer.json()["agents"][0]["oatr_issuer_id"] == "issuer-123"

    invalid_empty = await client.get("/api/v1/agents", params={"oatr_issuer_id": "   "})
    assert invalid_empty.status_code == 400
    assert invalid_empty.json()["detail"] == "oatr_issuer_id cannot be empty"
