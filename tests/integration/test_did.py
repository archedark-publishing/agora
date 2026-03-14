from __future__ import annotations

from ipaddress import ip_address

import agora.main as main_module


def payload(name: str, url: str, *, did: str | None = None) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "did", "name": "DID skill"}],
    }
    if did is not None:
        body["did"] = did
    return body


async def test_verify_did_web_success(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "DID Web Agent",
            "https://example.com/did-web-agent",
            did="did:web:did-agent.example",
        ),
        headers={"X-API-Key": "did-web-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    async def _fetch_doc(
        did_document_url: str,
        *,
        pinned_hostname: str,
        pinned_ip,
    ) -> dict[str, str]:
        assert did_document_url == "https://did-agent.example/.well-known/did.json"
        assert pinned_hostname == "did-agent.example"
        assert pinned_ip == ip_address("93.184.216.34")
        return {
            "id": "did:web:did-agent.example",
            "@context": "https://www.w3.org/ns/did/v1",
        }

    monkeypatch.setattr(main_module, "_fetch_did_web_document", _fetch_doc)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "did-web-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["verified"] is True
    assert verify.json()["did_verified"] is True

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:did-agent.example"
    assert detail.json()["did_verified"] is True

    verified_only = await client.get("/api/v1/agents", params={"did_verified": "true"})
    assert verified_only.status_code == 200
    assert verified_only.json()["total"] == 1
    assert verified_only.json()["agents"][0]["id"] == agent_id


async def test_verify_did_web_fails_on_id_mismatch(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "DID Mismatch Agent",
            "https://example.com/did-mismatch-agent",
            did="did:web:mismatch.example",
        ),
        headers={"X-API-Key": "did-mismatch-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    async def _fetch_doc(
        _did_document_url: str,
        *,
        pinned_hostname: str,
        pinned_ip,
    ) -> dict[str, str]:
        assert pinned_hostname == "mismatch.example"
        assert pinned_ip == ip_address("93.184.216.34")
        return {
            "id": "did:web:someone-else.example",
            "@context": "https://www.w3.org/ns/did/v1",
        }

    monkeypatch.setattr(main_module, "_fetch_did_web_document", _fetch_doc)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "did-mismatch-key"},
    )
    assert verify.status_code == 400
    assert "id does not match" in verify.json()["detail"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did_verified"] is False


async def test_verify_non_web_did_skips_verification(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "DID Key Agent",
            "https://example.com/did-key-agent",
            did="did:key:z6MkjchhfUsD6q7v",
        ),
        headers={"X-API-Key": "did-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "did-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["verified"] is False
    assert verify.json()["did_verified"] is False
    assert "verification skipped" in verify.json()["message"]

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did"] == "did:key:z6MkjchhfUsD6q7v"
    assert detail.json()["did_verified"] is False


async def test_has_did_filter_and_update_resets_did_verification(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "DID Reset Agent",
            "https://example.com/did-reset-agent",
            did="did:web:reset.example",
        ),
        headers={"X-API-Key": "did-reset-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    without_did = await client.post(
        "/api/v1/agents",
        json=payload("No DID Agent", "https://example.com/no-did-agent"),
        headers={"X-API-Key": "did-reset-key"},
    )
    assert without_did.status_code == 201

    async def _fetch_doc(
        _did_document_url: str,
        **_kwargs,
    ) -> dict[str, str]:
        return {
            "id": "did:web:reset.example",
            "@context": "https://www.w3.org/ns/did/v1",
        }

    monkeypatch.setattr(main_module, "_fetch_did_web_document", _fetch_doc)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "did-reset-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["did_verified"] is True

    has_did = await client.get("/api/v1/agents", params={"has_did": "true"})
    assert has_did.status_code == 200
    assert has_did.json()["total"] == 1
    assert has_did.json()["agents"][0]["id"] == agent_id

    no_did = await client.get("/api/v1/agents", params={"has_did": "false"})
    assert no_did.status_code == 200
    assert no_did.json()["total"] == 1
    assert no_did.json()["agents"][0]["id"] == without_did.json()["id"]

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "DID Reset Agent",
            "https://example.com/did-reset-agent",
            did="did:web:new-reset.example",
        ),
        headers={"X-API-Key": "did-reset-key"},
    )
    assert update.status_code == 200

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:new-reset.example"
    assert detail.json()["did_verified"] is False


async def test_registration_rejects_invalid_did_format(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Invalid DID Agent",
            "https://example.com/invalid-did-agent",
            did="example:alice",
        ),
        headers={"X-API-Key": "did-invalid-key"},
    )
    assert register.status_code == 400
    assert register.json()["detail"]["errors"][0]["field"] == "did"
