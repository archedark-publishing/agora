from __future__ import annotations

from ipaddress import ip_address

import agora.main as main_module


def payload(
    name: str,
    url: str,
    *,
    did: str | None = None,
    commitments_url: str | None = None,
) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "commitments", "name": "commitments skill"}],
    }
    if did is not None:
        body["did"] = did
    if commitments_url is not None:
        body["commitments_url"] = commitments_url
    return body


async def test_register_and_retrieve_commitments_url(client, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_verify_commitments_document(**kwargs) -> bool:
        calls.append(kwargs)
        return False

    monkeypatch.setattr(main_module, "verify_commitments_document", _fake_verify_commitments_document)

    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Commitment Agent",
            "https://example.com/commitment-agent",
            did="did:web:commitments.example",
            commitments_url="https://commitments.example/.well-known/agent-commitments.json",
        ),
        headers={"X-API-Key": "commitment-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    assert len(calls) == 1
    assert calls[0]["did_verified"] is False

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["commitments_url"] == "https://commitments.example/.well-known/agent-commitments.json"
    assert detail.json()["commitment_verified"] is False

    listing = await client.get("/api/v1/agents")
    assert listing.status_code == 200
    listed = next(agent for agent in listing.json()["agents"] if agent["id"] == agent_id)
    assert listed["commitments_url"] == "https://commitments.example/.well-known/agent-commitments.json"
    assert listed["commitment_verified"] is False


async def test_commitments_url_requires_basic_url_format(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Invalid Commitments Agent",
            "https://example.com/invalid-commitments-agent",
            commitments_url="not-a-url",
        ),
        headers={"X-API-Key": "invalid-commitment-key"},
    )
    assert register.status_code == 400
    assert register.json()["detail"]["message"] == "Invalid Agent Card"
    assert register.json()["detail"]["errors"][0]["field"] == "commitments_url"


async def test_verify_did_recomputes_commitment_verification(client, monkeypatch) -> None:
    async def _fake_verify_commitments_document(**kwargs) -> bool:
        return bool(kwargs["did_verified"]) and kwargs["did"] == "did:web:commitment-proof.example"

    async def _fetch_doc(
        did_document_url: str,
        *,
        pinned_hostname: str,
        pinned_ip,
    ) -> dict[str, str]:
        assert did_document_url == "https://commitment-proof.example/.well-known/did.json"
        assert pinned_hostname == "commitment-proof.example"
        assert pinned_ip == ip_address("93.184.216.34")
        return {
            "id": "did:web:commitment-proof.example",
            "@context": "https://www.w3.org/ns/did/v1",
        }

    monkeypatch.setattr(main_module, "verify_commitments_document", _fake_verify_commitments_document)
    monkeypatch.setattr(main_module, "_fetch_did_web_document", _fetch_doc)

    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Commitment Proof Agent",
            "https://example.com/commitment-proof-agent",
            did="did:web:commitment-proof.example",
            commitments_url="https://commitment-proof.example/.well-known/agent-commitments.json",
        ),
        headers={"X-API-Key": "commitment-proof-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "commitment-proof-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["did_verified"] is True
    assert verify.json()["commitment_verified"] is True

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did_verified"] is True
    assert detail.json()["commitment_verified"] is True


async def test_update_with_did_change_resets_commitment_verification(client, monkeypatch) -> None:
    async def _fake_verify_commitments_document(**kwargs) -> bool:
        return bool(kwargs["did_verified"])

    async def _fetch_doc(
        _did_document_url: str,
        **_kwargs,
    ) -> dict[str, str]:
        return {
            "id": "did:web:commitment-reset.example",
            "@context": "https://www.w3.org/ns/did/v1",
        }

    monkeypatch.setattr(main_module, "verify_commitments_document", _fake_verify_commitments_document)
    monkeypatch.setattr(main_module, "_fetch_did_web_document", _fetch_doc)

    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Commitment Reset Agent",
            "https://example.com/commitment-reset-agent",
            did="did:web:commitment-reset.example",
            commitments_url="https://commitment-reset.example/.well-known/agent-commitments.json",
        ),
        headers={"X-API-Key": "commitment-reset-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-did",
        headers={"X-API-Key": "commitment-reset-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["did_verified"] is True
    assert verify.json()["commitment_verified"] is True

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Commitment Reset Agent",
            "https://example.com/commitment-reset-agent",
            did="did:web:new-commitment-reset.example",
            commitments_url="https://commitment-reset.example/.well-known/agent-commitments.json",
        ),
        headers={"X-API-Key": "commitment-reset-key"},
    )
    assert update.status_code == 200

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["did"] == "did:web:new-commitment-reset.example"
    assert detail.json()["did_verified"] is False
    assert detail.json()["commitment_verified"] is False
