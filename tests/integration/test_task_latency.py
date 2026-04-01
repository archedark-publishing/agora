from __future__ import annotations


def payload(
    name: str,
    url: str,
    *,
    task_latency: dict | None | object = ...,
    snake_case_task_latency: bool = False,
) -> dict:
    body: dict[str, object] = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "weather", "name": "weather skill"}],
    }
    if task_latency is not ...:
        key = "task_latency" if snake_case_task_latency else "taskLatency"
        body[key] = task_latency
    return body


async def test_register_without_task_latency_keeps_field_optional(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("No Task Latency", "https://example.com/no-task-latency"),
        headers={"X-API-Key": "task-latency-none-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["taskLatency"] is None


async def test_register_and_update_task_latency_with_camel_case_field(client) -> None:
    task_latency = {
        "typicalSeconds": 14_400,
        "maxSeconds": 21_600,
        "scheduleBasis": "polling",
        "scheduleExpression": "0 */4 * * *",
    }

    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Task Latency Agent",
            "https://example.com/task-latency-agent",
            task_latency=task_latency,
        ),
        headers={"X-API-Key": "task-latency-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["taskLatency"] == task_latency

    clear_update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Task Latency Agent",
            "https://example.com/task-latency-agent",
            task_latency=None,
        ),
        headers={"X-API-Key": "task-latency-key"},
    )
    assert clear_update.status_code == 200

    cleared_detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert cleared_detail.status_code == 200
    assert cleared_detail.json()["taskLatency"] is None


async def test_register_accepts_snake_case_task_latency_alias(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Snake Task Latency",
            "https://example.com/snake-task-latency",
            task_latency={"scheduleBasis": "webhook"},
            snake_case_task_latency=True,
        ),
        headers={"X-API-Key": "task-latency-snake-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["taskLatency"] == {"scheduleBasis": "webhook"}


async def test_list_agents_filters_by_schedule_basis(client) -> None:
    polling = await client.post(
        "/api/v1/agents",
        json=payload(
            "Polling Agent",
            "https://example.com/polling-agent",
            task_latency={"scheduleBasis": "polling"},
        ),
        headers={"X-API-Key": "task-latency-filter-key"},
    )
    assert polling.status_code == 201

    streaming = await client.post(
        "/api/v1/agents",
        json=payload(
            "Streaming Agent",
            "https://example.com/streaming-agent",
            task_latency={"scheduleBasis": "streaming"},
        ),
        headers={"X-API-Key": "task-latency-filter-key"},
    )
    assert streaming.status_code == 201

    filtered = await client.get("/api/v1/agents", params={"schedule_basis": "polling"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["agents"][0]["name"] == "Polling Agent"
    assert filtered.json()["agents"][0]["taskLatency"] == {"scheduleBasis": "polling"}


async def test_task_latency_validation_rejects_unknown_schedule_basis_with_422(client) -> None:
    invalid = await client.post(
        "/api/v1/agents",
        json=payload(
            "Invalid Task Latency",
            "https://example.com/invalid-task-latency",
            task_latency={"scheduleBasis": "batch"},
        ),
        headers={"X-API-Key": "task-latency-invalid-key"},
    )
    assert invalid.status_code == 422

    register = await client.post(
        "/api/v1/agents",
        json=payload("Valid Update Target", "https://example.com/valid-update-target"),
        headers={"X-API-Key": "task-latency-update-invalid-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    invalid_update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Valid Update Target",
            "https://example.com/valid-update-target",
            task_latency={"scheduleBasis": "batch"},
        ),
        headers={"X-API-Key": "task-latency-update-invalid-key"},
    )
    assert invalid_update.status_code == 422
