from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.models import Agent
from agora.security import api_key_fingerprint, hash_api_key


def payload_for_recovery(url: str) -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": "Recovery Agent",
        "description": "Recovery flow test",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "recover", "name": "Recover"}],
    }


async def test_recovery_flow_rotates_key_and_invalidates_prior_token(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload_for_recovery("https://example.com/recovery-flow"),
        headers={"X-API-Key": "old-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    start1 = await client.post(f"/api/v1/agents/{agent_id}/recovery/start")
    start2 = await client.post(f"/api/v1/agents/{agent_id}/recovery/start")
    assert start1.status_code == 200
    assert start2.status_code == 200
    token1 = start1.json()["challenge_token"]
    token2 = start2.json()["challenge_token"]
    session1 = start1.json()["recovery_session_secret"]
    session2 = start2.json()["recovery_session_secret"]
    assert token1 != token2
    assert session1 != session2

    async def fetch_old(_url: str, **_kwargs: object) -> str:
        return token1

    monkeypatch.setattr(main_module, "_fetch_recovery_token", fetch_old)
    prior_complete = await client.post(
        f"/api/v1/agents/{agent_id}/recovery/complete",
        headers={
            "X-API-Key": "new-key",
            "X-Recovery-Session": session1,
        },
    )
    assert prior_complete.status_code == 400

    async def fetch_new(_url: str, **_kwargs: object) -> str:
        return token2

    monkeypatch.setattr(main_module, "_fetch_recovery_token", fetch_new)
    complete = await client.post(
        f"/api/v1/agents/{agent_id}/recovery/complete",
        headers={
            "X-API-Key": "new-key",
            "X-Recovery-Session": session2,
        },
    )
    assert complete.status_code == 200

    update_payload = payload_for_recovery("https://example.com/recovery-flow")
    old_key_update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=update_payload,
        headers={"X-API-Key": "old-key"},
    )
    assert old_key_update.status_code == 401

    new_key_update = await client.put(
        f"/api/v1/agents/{agent_id}",
        json=update_payload,
        headers={"X-API-Key": "new-key"},
    )
    assert new_key_update.status_code == 200


async def test_recovery_complete_rejects_expired_challenge(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload_for_recovery("https://example.com/recovery-expired"),
        headers={"X-API-Key": "old-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    start = await client.post(f"/api/v1/agents/{agent_id}/recovery/start")
    assert start.status_code == 200
    token = start.json()["challenge_token"]
    session_secret = start.json()["recovery_session_secret"]

    async with AsyncSessionLocal() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == agent_id))
        agent.recovery_challenge_hash = hash_api_key(token)
        agent.recovery_session_hash = api_key_fingerprint(session_secret)
        agent.recovery_challenge_created_at = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        agent.recovery_challenge_expires_at = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        await session.commit()

    async def fetch_token(_url: str, **_kwargs: object) -> str:
        return token

    monkeypatch.setattr(main_module, "_fetch_recovery_token", fetch_token)
    complete = await client.post(
        f"/api/v1/agents/{agent_id}/recovery/complete",
        headers={
            "X-API-Key": "brand-new-key",
            "X-Recovery-Session": session_secret,
        },
    )
    assert complete.status_code == 400


async def test_recovery_complete_rejects_incorrect_session_secret(client, monkeypatch) -> None:
    register = await client.post(
        "/api/v1/agents",
        json=payload_for_recovery("https://example.com/recovery-session"),
        headers={"X-API-Key": "old-key"},
    )
    assert register.status_code == 201
    agent_id = register.json()["id"]

    start = await client.post(f"/api/v1/agents/{agent_id}/recovery/start")
    assert start.status_code == 200
    token = start.json()["challenge_token"]

    async def fetch_token(_url: str, **_kwargs: object) -> str:
        return token

    monkeypatch.setattr(main_module, "_fetch_recovery_token", fetch_token)
    complete = await client.post(
        f"/api/v1/agents/{agent_id}/recovery/complete",
        headers={
            "X-API-Key": "brand-new-key",
            "X-Recovery-Session": "wrong-session-secret",
        },
    )
    assert complete.status_code == 400
