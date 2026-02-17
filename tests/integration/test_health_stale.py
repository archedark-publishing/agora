from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agora.database import AsyncSessionLocal
from agora.models import Agent


def payload(name: str, url: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "stale-test", "name": "Stale Test"}],
    }


async def test_stale_filter_and_unknown_behavior(client) -> None:
    # Create three agents through API.
    created_ids: list[str] = []
    for name, url in [
        ("unknown-agent", "https://example.com/stale/unknown"),
        ("never-healthy-stale", "https://example.com/stale/never"),
        ("recent-unhealthy", "https://example.com/stale/recent"),
    ]:
        response = await client.post(
            "/api/v1/agents",
            json=payload(name, url),
            headers={"X-API-Key": "stale-key"},
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    unknown_id, never_stale_id, recent_unhealthy_id = created_ids
    now = datetime.now(tz=timezone.utc)

    async with AsyncSessionLocal() as session:
        unknown = await session.scalar(select(Agent).where(Agent.id == unknown_id))
        never_stale = await session.scalar(select(Agent).where(Agent.id == never_stale_id))
        recent = await session.scalar(select(Agent).where(Agent.id == recent_unhealthy_id))

        unknown.health_status = "unknown"
        unknown.registered_at = now - timedelta(days=30)
        unknown.last_healthy_at = None

        never_stale.health_status = "unhealthy"
        never_stale.registered_at = now - timedelta(days=9)
        never_stale.last_healthy_at = None

        recent.health_status = "unhealthy"
        recent.registered_at = now - timedelta(days=9)
        recent.last_healthy_at = now - timedelta(days=2)
        await session.commit()

    unknown_detail = await client.get(f"/api/v1/agents/{unknown_id}")
    assert unknown_detail.status_code == 200
    assert unknown_detail.json()["is_stale"] is False
    assert unknown_detail.json()["stale_days"] == 0

    stale_true = await client.get("/api/v1/agents", params={"stale": "true"})
    assert stale_true.status_code == 200
    stale_true_ids = {agent["id"] for agent in stale_true.json()["agents"]}
    assert never_stale_id in stale_true_ids
    assert unknown_id not in stale_true_ids
    assert recent_unhealthy_id not in stale_true_ids

    stale_false = await client.get("/api/v1/agents", params={"stale": "false"})
    assert stale_false.status_code == 200
    stale_false_ids = {agent["id"] for agent in stale_false.json()["agents"]}
    assert unknown_id in stale_false_ids
    assert recent_unhealthy_id in stale_false_ids
