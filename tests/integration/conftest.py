from __future__ import annotations

import ipaddress

import httpx
import pytest_asyncio
from sqlalchemy import delete, text

import agora.main as main_module
from agora.database import AsyncSessionLocal, close_engine
from agora.main import app
from agora.models import Agent, AgentIncident, AgentReliabilityReport


@pytest_asyncio.fixture(autouse=True)
async def clean_state(monkeypatch) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(AgentIncident))
            await session.execute(delete(AgentReliabilityReport))
            await session.execute(delete(Agent))
            await session.execute(text("REFRESH MATERIALIZED VIEW agent_reliability_scores"))
        except Exception:
            # Migration may not be applied in all test contexts.
            await session.rollback()
            await session.execute(delete(Agent))
        await session.commit()

    monkeypatch.setattr(
        "agora.url_safety._resolve_ips",
        lambda _hostname: [ipaddress.ip_address("93.184.216.34")],
    )
    await main_module.rate_limiter.reset()
    main_module.query_tracker._last_queried.clear()
    main_module.latest_registry_snapshot = None
    main_module.request_metrics.clear()
    yield
    await close_engine()


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
