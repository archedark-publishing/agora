from __future__ import annotations

import httpx

from agora.main import app


async def test_well_known_did_json_without_key() -> None:
    """When no public key is configured, serve the base DID document."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/did.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/did+json")

    payload = response.json()
    assert payload["@context"] == ["https://www.w3.org/ns/did/v1"]
    assert payload["id"] == "did:web:the-agora.dev"
    assert payload["service"] == [
        {
            "id": "did:web:the-agora.dev#registry",
            "type": "AgentRegistry",
            "serviceEndpoint": "https://the-agora.dev",
        }
    ]
    # No verificationMethod when key is absent
    assert "verificationMethod" not in payload
    assert "authentication" not in payload
    assert "assertionMethod" not in payload


async def test_well_known_did_json_with_verification_method(monkeypatch) -> None:
    """When a public key is configured, include verificationMethod fields."""
    test_key = "z6MktestKeyForUnitTestsOnly1234567890abcdefg"
    monkeypatch.setenv("DID_PUBLIC_KEY_MULTIBASE", test_key)

    # Clear the settings cache so monkeypatched env is picked up
    from agora.config import get_settings
    get_settings.cache_clear()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/.well-known/did.json")

        assert response.status_code == 200
        payload = response.json()

        # Extended context
        assert "https://w3id.org/security/suites/ed25519-2020/v1" in payload["@context"]

        # verificationMethod present and correct
        assert len(payload["verificationMethod"]) == 1
        vm = payload["verificationMethod"][0]
        assert vm["id"] == "did:web:the-agora.dev#key-1"
        assert vm["type"] == "Ed25519VerificationKey2020"
        assert vm["controller"] == "did:web:the-agora.dev"
        assert vm["publicKeyMultibase"] == test_key

        # authentication and assertionMethod reference the key
        assert payload["authentication"] == ["did:web:the-agora.dev#key-1"]
        assert payload["assertionMethod"] == ["did:web:the-agora.dev#key-1"]

        # @context is the first key in the JSON output
        keys = list(payload.keys())
        assert keys[0] == "@context"
    finally:
        # Restore clean settings cache
        monkeypatch.delenv("DID_PUBLIC_KEY_MULTIBASE", raising=False)
        get_settings.cache_clear()
