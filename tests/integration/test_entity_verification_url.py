from __future__ import annotations


def payload(
    name: str,
    url: str,
    *,
    entity_verification_url: str | None = None,
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
    if entity_verification_url is not None:
        body["entity_verification_url"] = entity_verification_url
    return body


async def test_register_and_retrieve_entity_verification_url(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Entity Agent",
            "https://example.com/entity-agent",
            entity_verification_url="https://api.corpo.llc/api/v1/entities/123/verify",
        ),
        headers={"X-API-Key": "entity-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["entity_verification_url"] == "https://api.corpo.llc/api/v1/entities/123/verify"

    listing = await client.get("/api/v1/agents")
    assert listing.status_code == 200
    listed = next(agent for agent in listing.json()["agents"] if agent["id"] == agent_id)
    assert listed["entity_verification_url"] == "https://api.corpo.llc/api/v1/entities/123/verify"


async def test_register_without_entity_verification_url_defaults_to_none(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("No Entity Agent", "https://example.com/no-entity-agent"),
        headers={"X-API-Key": "entity-key-2"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["entity_verification_url"] is None


async def test_patch_accepts_entity_verification_url(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("Patch Entity Agent", "https://example.com/patch-entity-agent"),
        headers={"X-API-Key": "patch-entity-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    patch = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Patch Entity Agent",
            "https://example.com/patch-entity-agent",
            entity_verification_url="https://api.corpo.llc/api/v1/entities/xyz/verify",
        ),
        headers={"X-API-Key": "patch-entity-key"},
    )
    assert patch.status_code == 200

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["entity_verification_url"] == "https://api.corpo.llc/api/v1/entities/xyz/verify"


async def test_entity_verification_url_requires_basic_url_format(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Invalid Entity Agent",
            "https://example.com/invalid-entity-agent",
            entity_verification_url="not-a-url",
        ),
        headers={"X-API-Key": "invalid-entity-key"},
    )
    assert register.status_code == 400
    assert register.json()["detail"]["message"] == "Invalid Agent Card"
    assert register.json()["detail"]["errors"][0]["field"] == "entity_verification_url"
