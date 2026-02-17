from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agora.database import AsyncSessionLocal
from agora.models import Agent


def payload(name: str, url: str, skill_id: str, tags: list[str], capabilities: dict[str, bool]) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": capabilities,
        "skills": [{"id": skill_id, "name": f"{skill_id} name", "tags": tags}],
    }


async def test_search_semantics_and_default_ordering(client) -> None:
    specs = [
        ("healthy-new", "https://example.com/search/healthy-new", "skill-weather", ["alpha"], {"streaming": True}),
        ("healthy-old", "https://example.com/search/healthy-old", "skill-translate", ["beta"], {"batch": True}),
        ("unknown-new", "https://example.com/search/unknown-new", "skill-weather", ["gamma"], {"streaming": True}),
        ("unhealthy-recent", "https://example.com/search/unhealthy-recent", "skill-research", ["delta"], {"streaming": True}),
        ("unhealthy-stale-lasthealthy", "https://example.com/search/unhealthy-stale-lasthealthy", "skill-weather", ["epsilon"], {"batch": True}),
        ("unhealthy-stale-never", "https://example.com/search/unhealthy-stale-never", "skill-translate", ["zeta"], {"streaming": True}),
    ]

    ids: dict[str, str] = {}
    for name, url, skill, tags, caps in specs:
        response = await client.post(
            "/api/v1/agents",
            json=payload(name, url, skill, tags, caps),
            headers={"X-API-Key": "search-key"},
        )
        assert response.status_code == 201
        ids[name] = response.json()["id"]

    now = datetime.now(tz=timezone.utc)
    async with AsyncSessionLocal() as session:
        rows = list((await session.scalars(select(Agent))).all())
        by_name = {row.name: row for row in rows}

        by_name["healthy-new"].health_status = "healthy"
        by_name["healthy-new"].registered_at = now - timedelta(hours=1)
        by_name["healthy-new"].last_healthy_at = now - timedelta(hours=1)

        by_name["healthy-old"].health_status = "healthy"
        by_name["healthy-old"].registered_at = now - timedelta(hours=3)
        by_name["healthy-old"].last_healthy_at = now - timedelta(hours=3)

        by_name["unknown-new"].health_status = "unknown"
        by_name["unknown-new"].registered_at = now - timedelta(hours=2)
        by_name["unknown-new"].last_healthy_at = None

        by_name["unhealthy-recent"].health_status = "unhealthy"
        by_name["unhealthy-recent"].registered_at = now - timedelta(days=1)
        by_name["unhealthy-recent"].last_healthy_at = now - timedelta(days=2)

        by_name["unhealthy-stale-lasthealthy"].health_status = "unhealthy"
        by_name["unhealthy-stale-lasthealthy"].registered_at = now - timedelta(days=10)
        by_name["unhealthy-stale-lasthealthy"].last_healthy_at = now - timedelta(days=8)

        by_name["unhealthy-stale-never"].health_status = "unhealthy"
        by_name["unhealthy-stale-never"].registered_at = now - timedelta(days=9)
        by_name["unhealthy-stale-never"].last_healthy_at = None

        await session.commit()

    default = await client.get("/api/v1/agents", params={"limit": 50})
    assert default.status_code == 200
    names = [agent["name"] for agent in default.json()["agents"]]
    assert names == [
        "healthy-new",
        "healthy-old",
        "unknown-new",
        "unhealthy-recent",
        "unhealthy-stale-never",
        "unhealthy-stale-lasthealthy",
    ]

    skill_or = await client.get(
        "/api/v1/agents",
        params=[("skill", "skill-weather"), ("skill", "skill-translate")],
    )
    assert skill_or.status_code == 200
    assert skill_or.json()["total"] == 5

    and_filters = await client.get(
        "/api/v1/agents",
        params=[("skill", "skill-weather"), ("capability", "batch")],
    )
    assert and_filters.status_code == 200
    assert and_filters.json()["total"] == 1
    assert and_filters.json()["agents"][0]["name"] == "unhealthy-stale-lasthealthy"

    ilike_q = await client.get("/api/v1/agents", params={"q": "EPSILON"})
    assert ilike_q.status_code == 200
    assert ilike_q.json()["total"] == 1
    assert ilike_q.json()["agents"][0]["name"] == "unhealthy-stale-lasthealthy"
