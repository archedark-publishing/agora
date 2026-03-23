from __future__ import annotations

import httpx

from agora.main import app


async def test_well_known_did_json_route() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/did.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/did+json")

    payload = response.json()
    assert payload == {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": "did:web:the-agora.dev",
        "service": [
            {
                "id": "did:web:the-agora.dev#registry",
                "type": "AgentRegistry",
                "serviceEndpoint": "https://the-agora.dev",
            }
        ],
    }
