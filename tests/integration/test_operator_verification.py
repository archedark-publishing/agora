from __future__ import annotations

import agora.main as main_module


def payload(
    name: str,
    url: str,
    *,
    operator: dict[str, str | bool] | None = None,
) -> dict:
    body = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": f"{name} description",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "operator", "name": "operator skill"}],
    }
    if operator is not None:
        body["operator"] = operator
    return body


async def test_operator_verification_via_well_known(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Operator Agent",
            "https://example.com/operator-agent",
            operator={
                "name": "Josh Edwards",
                "url": "https://exe.xyz",
                "verified": True,
            },
        ),
        headers={"X-API-Key": "operator-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    detail_before = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail_before.status_code == 200
    assert detail_before.json()["operator"] == {
        "name": "Josh Edwards",
        "url": "https://exe.xyz/",
        "verified": False,
    }

    challenge = await client.get(
        f"/api/v1/agents/{agent_id}/operator-challenge",
        headers={"X-API-Key": "operator-key"},
    )
    assert challenge.status_code == 200
    challenge_token = challenge.json()["token"]
    assert challenge_token.startswith("agora_verify_")
    assert challenge.json()["expires_at"]

    async def _no_dns(_domain: str) -> list[str]:
        return []

    async def _well_known(_operator_url: str) -> list[str]:
        return [challenge_token]

    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_dns", _no_dns)
    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_well_known", _well_known)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-operator",
        headers={"X-API-Key": "operator-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["verified"] is True

    detail_after = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail_after.status_code == 200
    assert detail_after.json()["operator"] == {
        "name": "Josh Edwards",
        "url": "https://exe.xyz/",
        "verified": True,
    }
    assert detail_after.json()["agent_card"]["operator"]["verified"] is True

    verified_only = await client.get("/api/v1/agents", params={"operator_verified": "true"})
    assert verified_only.status_code == 200
    assert verified_only.json()["total"] == 1
    assert verified_only.json()["agents"][0]["id"] == agent_id


async def test_operator_verification_via_dns_txt(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Operator DNS Agent",
            "https://example.com/operator-agent-dns",
            operator={
                "name": "DNS Operator",
                "url": "https://operator.example",
            },
        ),
        headers={"X-API-Key": "operator-dns-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    challenge = await client.get(
        f"/api/v1/agents/{agent_id}/operator-challenge",
        headers={"X-API-Key": "operator-dns-key"},
    )
    assert challenge.status_code == 200
    challenge_token = challenge.json()["token"]

    async def _dns(_domain: str) -> list[str]:
        return [challenge_token]

    async def _no_well_known(_operator_url: str) -> list[str]:
        return []

    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_dns", _dns)
    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_well_known", _no_well_known)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-operator",
        headers={"X-API-Key": "operator-dns-key"},
    )
    assert verify.status_code == 200
    assert verify.json()["verified"] is True


async def test_operator_challenge_requires_operator_claim(client) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload("No Operator Agent", "https://example.com/no-operator"),
        headers={"X-API-Key": "no-operator-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    challenge = await client.get(
        f"/api/v1/agents/{agent_id}/operator-challenge",
        headers={"X-API-Key": "no-operator-key"},
    )
    assert challenge.status_code == 400


async def test_update_operator_claim_resets_verification(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload(
            "Operator Update Agent",
            "https://example.com/operator-update-agent",
            operator={
                "name": "Update Operator",
                "url": "https://operator.example",
            },
        ),
        headers={"X-API-Key": "operator-update-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    challenge = await client.get(
        f"/api/v1/agents/{agent_id}/operator-challenge",
        headers={"X-API-Key": "operator-update-key"},
    )
    assert challenge.status_code == 200
    challenge_token = challenge.json()["token"]

    async def _no_dns(_domain: str) -> list[str]:
        return []

    async def _well_known(_operator_url: str) -> list[str]:
        return [challenge_token]

    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_dns", _no_dns)
    monkeypatch.setattr(main_module, "_fetch_operator_verification_tokens_from_well_known", _well_known)

    verify = await client.post(
        f"/api/v1/agents/{agent_id}/verify-operator",
        headers={"X-API-Key": "operator-update-key"},
    )
    assert verify.status_code == 200

    update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=payload(
            "Operator Update Agent",
            "https://example.com/operator-update-agent",
            operator={
                "name": "Update Operator",
                "url": "https://operator-new.example",
            },
        ),
        headers={"X-API-Key": "operator-update-key"},
    )
    assert update.status_code == 200

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["operator"] == {
        "name": "Update Operator",
        "url": "https://operator-new.example/",
        "verified": False,
    }

    verified_only = await client.get("/api/v1/agents", params={"operator_verified": "true"})
    assert verified_only.status_code == 200
    assert verified_only.json()["total"] == 0
