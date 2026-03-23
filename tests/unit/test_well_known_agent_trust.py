from __future__ import annotations

import httpx

from agora.main import app


async def test_well_known_agent_trust_json() -> None:
    """OATR domain verification endpoint returns correct issuer binding."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/agent-trust.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    payload = response.json()
    assert payload["issuer_id"] == "agora"
    assert payload["public_key_fingerprint"] == "agora-2026-03"
