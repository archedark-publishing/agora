"""Owner edits and verify-before-replace contact changes for minimal listings."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.models import Agent
from agora.security import hash_api_key
from tests.integration.test_lifecycle import build_payload
from tests.integration.test_minimal_directory import (
    _minimal_payload,
    _register_minimal,
    capture_verification_email,
)

OWNER = {"X-API-Key": "minimal-test-key"}


def _path(agent):
    return f"/api/v1/agents/{agent['id']}/minimal"


async def test_profile_patch_keeps_identity_and_updates_public_feeds(client, capture_verification_email):
    agent = await _register_minimal(client)
    changes = {"name": "Ada Updated", "description": None, "response_sla": None,
               "location": "Boston", "capabilities": []}
    response = await client.patch(_path(agent), json=changes, headers=OWNER)
    assert response.status_code == 200, response.text
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["id"] == agent["id"]
    assert detail["directory_slug"] == agent["directory_slug"]
    assert detail["email"] == agent["email"]
    for field, value in changes.items():
        assert response.json()[field] == value
        if field in ("name", "description", "capabilities"):
            expected = None if value == [] else value
            assert detail["agent_card"].get(field) == expected
        else:
            assert detail[field] == value
    feed = (await client.get("/agents.json")).json()["agents"][0]
    assert feed["name"] == changes["name"]
    assert feed["location"] == "Boston"
    assert feed["capabilities"] == []
    assert len(capture_verification_email) == 1


@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "", None), ("PATCH", "", {"name": "Intruder"}),
    ("DELETE", "/pending-email", None), ("POST", "/pending-email/resend", None),
])
async def test_owner_routes_require_matching_key(client, capture_verification_email, method, suffix, body):
    agent = await _register_minimal(client)
    response = await client.request(method, _path(agent) + suffix, json=body,
                                    headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


async def test_profile_patch_is_limited_to_twenty_per_key(client, capture_verification_email):
    agent = await _register_minimal(client)
    for index in range(20):
        response = await client.patch(_path(agent), json={"name": f"Edit {index}"}, headers=OWNER)
        assert response.status_code == 200, response.text
    response = await client.patch(_path(agent), json={"name": "One too many"}, headers=OWNER)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["agent_card"]["name"] == "Edit 19"


async def test_invalid_keys_hit_ip_limit_before_owner_lookup(client, capture_verification_email, monkeypatch):
    agent = await _register_minimal(client)
    monkeypatch.setattr(main_module, "MINIMAL_OWNER_RATE_LIMIT_PER_IP", 2)
    for index in range(2):
        response = await client.get(_path(agent), headers={"X-API-Key": f"bad-key-{index}"})
        assert response.status_code == 401

    async def should_not_lookup(*args, **kwargs):
        raise AssertionError("owner lookup ran after the IP limit")

    monkeypatch.setattr(main_module, "_owned_minimal_agent", should_not_lookup)
    response = await client.get(_path(agent), headers={"X-API-Key": "third-bad-key"})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


async def test_owner_lookup_locks_only_after_authentication():
    agent = SimpleNamespace(owner_key_hash=hash_api_key("right-key"), agent_card={"directory_listing": True})
    session = SimpleNamespace(get=AsyncMock(return_value=agent), scalar=AsyncMock(return_value=agent))
    with pytest.raises(HTTPException) as error:
        await main_module._owned_minimal_agent(session, "agent-id", "wrong-key", for_update=True)
    assert error.value.status_code == 401
    session.scalar.assert_not_awaited()
    assert await main_module._owned_minimal_agent(session, "agent-id", "right-key") is agent
    session.scalar.assert_not_awaited()
    assert await main_module._owned_minimal_agent(session, "agent-id", "right-key", for_update=True) is agent
    session.scalar.assert_awaited_once()
    session.scalar.reset_mock()
    session.scalar.return_value = SimpleNamespace(
        owner_key_hash=hash_api_key("new-owner-key"), agent_card={"directory_listing": True},
    )
    with pytest.raises(HTTPException) as error:
        await main_module._owned_minimal_agent(session, "agent-id", "right-key", for_update=True)
    assert error.value.status_code == 401
    session.scalar.assert_awaited_once()


async def test_pending_email_requests_and_resends_share_five_per_listing(client, capture_verification_email):
    agent = await _register_minimal(client)
    for index in range(3):
        response = await client.patch(_path(agent), headers=OWNER,
                                      json={"email": f"change-{index}@example.com"})
        assert response.status_code == 200, response.text
    for _ in range(2):
        response = await client.post(_path(agent) + "/pending-email/resend", headers=OWNER)
        assert response.status_code == 200, response.text
    response = await client.post(_path(agent) + "/pending-email/resend", headers=OWNER)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize("payload", [
    {"name": ""}, {"name": None}, {"email": "invalid"}, {"email": None},
    {"url": "https://example.com"}, {"descripton": "typo"},
    {"capabilities": "email"},
])
async def test_patch_rejects_invalid_or_unsupported_fields(client, capture_verification_email, payload):
    agent = await _register_minimal(client)
    response = await client.patch(_path(agent), json=payload, headers=OWNER)
    assert response.status_code == 400, response.text
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["agent_card"]["name"] == agent["name"]
    assert detail["email"] == agent["email"]


async def test_full_card_cannot_use_minimal_patch(client):
    response = await client.post("/api/v1/agents", headers=OWNER,
        json=build_payload("Full Agent", "https://example.com/a2a"))
    assert response.status_code == 201, response.text
    response = await client.patch(_path(response.json()), headers=OWNER, json={"name": "Changed"})
    assert response.status_code == 409


async def test_email_change_preserves_public_contact_until_confirmation(client, capture_verification_email):
    agent = await _register_minimal(client)
    original_link = capture_verification_email[-1]["verify_url"]
    assert (await client.get(original_link)).status_code == 200
    assert (await client.get(original_link)).status_code == 200
    response = await client.patch(_path(agent), headers=OWNER,
        json={"email": "new@example.com", "description": "Updated immediately"})
    assert response.status_code == 200, response.text
    assert response.json()["pending_email"] == "new@example.com"
    assert response.json()["verification_email_sent"] is True
    owner = await client.get(_path(agent), headers=OWNER)
    assert owner.json()["pending_email"] == "new@example.com"
    for url in (f"/api/v1/agents/{agent['id']}", "/agents.json", "/api/v1/registry.json"):
        public = await client.get(url)
        assert public.status_code == 200
        assert "new@example.com" not in public.text
        assert "pending_email" not in public.text
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["email"] == "ada@example.com"
    assert detail["email_verified"] is True
    assert detail["agent_card"]["description"] == "Updated immediately"
    replacement_link = capture_verification_email[-1]["verify_url"]
    assert (await client.get(replacement_link)).status_code == 200
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["email"] == "new@example.com"
    assert detail["email_verified"] is True
    assert detail["directory_slug"] == agent["directory_slug"]
    assert (await client.get(_path(agent), headers=OWNER)).json()["pending_email"] is None
    assert (await client.get(replacement_link)).status_code == 400
    assert (await client.get(original_link)).status_code == 400
    async with AsyncSessionLocal() as session:
        stored = await session.scalar(select(Agent).where(Agent.email == "new@example.com"))
        assert stored is not None
        assert stored.agent_card["email"] == "new@example.com"


async def test_latest_request_and_cancel_invalidate_links(client, capture_verification_email):
    agent = await _register_minimal(client)
    for email in ("new@example.com", "new@example.com", "latest@example.com"):
        response = await client.patch(_path(agent), headers=OWNER, json={"email": email})
        assert response.status_code == 200, response.text
    for sent in capture_verification_email[1:-1]:
        assert (await client.get(sent["verify_url"])).status_code == 400
    latest_link = capture_verification_email[-1]["verify_url"]
    cancelled = await client.delete(_path(agent) + "/pending-email", headers=OWNER)
    assert cancelled.status_code in (200, 204), cancelled.text
    assert (await client.get(latest_link)).status_code == 400
    assert (await client.get(_path(agent), headers=OWNER)).json()["pending_email"] is None


async def test_failed_delivery_can_be_retried_without_losing_contact(client, capture_verification_email, monkeypatch):
    agent = await _register_minimal(client)
    send = main_module._send_verification_email
    async def fail(**kwargs):
        return False
    monkeypatch.setattr(main_module, "_send_verification_email", fail)
    response = await client.patch(_path(agent), headers=OWNER, json={"email": "retry@example.com"})
    assert response.status_code == 200, response.text
    assert response.json()["verification_email_sent"] is False
    assert response.json()["pending_email"] == "retry@example.com"
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["email"] == "ada@example.com"
    monkeypatch.setattr(main_module, "_send_verification_email", send)
    resent = await client.post(_path(agent) + "/pending-email/resend", headers=OWNER)
    assert resent.status_code == 200, resent.text
    assert resent.json()["verification_email_sent"] is True
    assert capture_verification_email[-1]["to_email"] == "retry@example.com"
    assert (await client.get(capture_verification_email[-1]["verify_url"])).status_code == 200


async def test_expired_pending_link_cannot_replace_contact(client, capture_verification_email, monkeypatch):
    agent = await _register_minimal(client)
    monkeypatch.setattr(main_module.settings, "email_verification_ttl_hours", -1)
    response = await client.patch(_path(agent), headers=OWNER, json={"email": "expired@example.com"})
    assert response.status_code == 200, response.text
    assert (await client.get(capture_verification_email[-1]["verify_url"])).status_code == 400
    assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["email"] == "ada@example.com"


async def test_email_collision_checked_at_request_and_confirmation(client, capture_verification_email):
    agent = await _register_minimal(client)
    await _register_minimal(client, _minimal_payload("Other", "taken@example.com"), "other-key")
    conflict = await client.patch(_path(agent), headers=OWNER, json={"email": "TAKEN@example.com"})
    assert conflict.status_code == 409, conflict.text
    pending = await client.patch(_path(agent), headers=OWNER, json={"email": "race@example.com"})
    assert pending.status_code == 200, pending.text
    link = capture_verification_email[-1]["verify_url"]
    await _register_minimal(client, _minimal_payload("Racer", "race@example.com"), "race-key")
    confirmation = await client.get(link)
    assert confirmation.status_code == 409, confirmation.text
    assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["email"] == "ada@example.com"


async def test_concurrent_confirmations_have_only_one_winner(client, capture_verification_email):
    first = await _register_minimal(client)
    second = await _register_minimal(client, _minimal_payload("Second", "second@example.com"), "second-key")
    links = []
    for agent, headers in ((first, OWNER), (second, {"X-API-Key": "second-key"})):
        response = await client.patch(_path(agent), headers=headers, json={"email": "shared@example.com"})
        assert response.status_code == 200, response.text
        links.append(capture_verification_email[-1]["verify_url"])
    responses = await asyncio.gather(*(client.get(link) for link in links))
    assert sorted(response.status_code for response in responses) == [200, 409]
    details = [(await client.get(f"/api/v1/agents/{agent['id']}")).json() for agent in (first, second)]
    assert sum(detail["email"] == "shared@example.com" for detail in details) == 1
    for index, response in enumerate(responses):
        if response.status_code == 409:
            assert details[index]["email"] == (first, second)[index]["email"]


async def test_returning_to_original_address_does_not_revive_registration_token(client, capture_verification_email):
    agent = await _register_minimal(client)
    registration_link = capture_verification_email[-1]["verify_url"]
    assert (await client.get(registration_link)).status_code == 200
    for email in ("replacement@example.com", "ada@example.com"):
        response = await client.patch(_path(agent), headers=OWNER, json={"email": email})
        assert response.status_code == 200, response.text
        assert (await client.get(capture_verification_email[-1]["verify_url"])).status_code == 200
    assert (await client.get(registration_link)).status_code == 400
    detail = (await client.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["email"] == "ada@example.com"
    assert detail["email_verified"] is True


async def test_database_rejects_case_insensitive_email_duplicates(client, capture_verification_email):
    await _register_minimal(client)
    await _register_minimal(client, _minimal_payload("Second", "second@example.com"), "second-key")
    async with AsyncSessionLocal() as session:
        with pytest.raises(IntegrityError):
            await session.execute(update(Agent).where(Agent.email == "second@example.com").values(email="ADA@EXAMPLE.COM"))
            await session.commit()
        await session.rollback()
    async with AsyncSessionLocal() as session:
        emails = (await session.scalars(select(Agent.email))).all()
        assert sorted(emails) == ["ada@example.com", "second@example.com"]
