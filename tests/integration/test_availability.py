from __future__ import annotations


def payload(name: str, url: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "weather skill"}],
    }


async def test_register_with_availability_and_return_in_detail_and_list(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json={
            **payload("Availability Agent", "https://example.com/availability-agent"),
            "availability": {
                "schedule_type": "cron",
                "cron_expression": "0 */4 * * *",
                "timezone": "America/New_York",
                "next_active_at": "2026-03-20T16:00:00Z",
                "last_active_at": "2026-03-20T12:00:00Z",
                "task_latency_max_seconds": 14400,
            },
        },
        headers={"X-API-Key": "availability-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    availability = detail.json()["availability"]
    assert availability["schedule_type"] == "cron"
    assert availability["cron_expression"] == "0 */4 * * *"
    assert availability["timezone"] == "America/New_York"
    assert availability["task_latency_max_seconds"] == 14400
    assert availability["next_active_at"].startswith("2026-03-20T16:00:00")
    assert availability["last_active_at"].startswith("2026-03-20T12:00:00")

    listing = await client.get("/api/v1/agents")
    assert listing.status_code == 200
    row = next(agent for agent in listing.json()["agents"] if agent["id"] == agent_id)
    assert row["availability"]["schedule_type"] == "cron"


async def test_register_without_availability_is_backward_compatible(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("No Availability Agent", "https://example.com/no-availability-agent"),
        headers={"X-API-Key": "no-availability-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["availability"] is None


async def test_register_with_partial_availability(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json={
            **payload("Partial Availability Agent", "https://example.com/partial-availability-agent"),
            "availability": {
                "schedule_type": "manual",
            },
        },
        headers={"X-API-Key": "partial-availability-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["availability"] == {"schedule_type": "manual"}


async def test_register_rejects_invalid_availability_values(client) -> None:
    invalid_cron = await client.post(
        "/api/v1/agents",
        json={
            **payload("Invalid Cron Agent", "https://example.com/invalid-cron-agent"),
            "availability": {
                "schedule_type": "cron",
                "cron_expression": "not-a-cron",
            },
        },
        headers={"X-API-Key": "invalid-cron-key"},
    )
    assert invalid_cron.status_code == 400
    assert invalid_cron.json()["detail"]["message"] == "Invalid availability metadata"
    assert any(
        error["field"] == "availability.cron_expression"
        for error in invalid_cron.json()["detail"]["errors"]
    )

    invalid_datetime = await client.post(
        "/api/v1/agents",
        json={
            **payload("Invalid Date Agent", "https://example.com/invalid-date-agent"),
            "availability": {
                "next_active_at": "not-an-iso-datetime",
            },
        },
        headers={"X-API-Key": "invalid-date-key"},
    )
    assert invalid_datetime.status_code == 400
    assert invalid_datetime.json()["detail"]["message"] == "Invalid availability metadata"
    assert any(
        error["field"] == "availability.next_active_at"
        for error in invalid_datetime.json()["detail"]["errors"]
    )


async def test_heartbeat_updates_availability_last_active_at(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("Heartbeat Agent", "https://example.com/heartbeat-agent"),
        headers={"X-API-Key": "heartbeat-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    heartbeat = await client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={
            "last_active_at": "2026-03-20T16:10:00Z",
            "next_active_at": "2026-03-20T20:00:00Z",
        },
        headers={"X-API-Key": "heartbeat-key"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["availability"]["last_active_at"].startswith("2026-03-20T16:10:00")
    assert heartbeat.json()["availability"]["next_active_at"].startswith("2026-03-20T20:00:00")

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["availability"]["last_active_at"].startswith("2026-03-20T16:10:00")
