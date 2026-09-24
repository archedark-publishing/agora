"""Integration tests for the Agora v2 minimal directory endpoints."""

from __future__ import annotations

import httpx
import pytest


class _FakeChallengeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _FakeChallengeClient:
    """Stands in for httpx.AsyncClient during email-challenge verification."""

    published: str = ""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeChallengeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url: str) -> _FakeChallengeResponse:
        return _FakeChallengeResponse(type(self).published)


def _minimal_payload(name: str = "Ada", email: str = "ada@example.com") -> dict:
    return {
        "name": name,
        "description": "A helpful agent",
        "email": email,
        "response_sla": "within 4 hours",
        "capabilities": ["email", "scheduling"],
    }


async def _register_minimal(client, payload=None, api_key="minimal-test-key") -> dict:
    response = await client.post(
        "/api/v1/agents/minimal",
        json=payload or _minimal_payload(),
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_minimal_registration_happy_path(client) -> None:
    body = await _register_minimal(client)
    assert body["name"] == "Ada"
    assert body["directory_slug"] == "ada"
    assert body["email_challenge"]
    assert "verify-email" in body["verification_instructions"]

    detail = await client.get(f"/api/v1/agents/{body['id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["email"] == "ada@example.com"
    assert payload["response_sla"] == "within 4 hours"
    assert payload["email_verified"] is False
    assert payload["directory_slug"] == "ada"
    assert payload["url"] is None


async def test_minimal_registration_validation(client) -> None:
    missing_name = _minimal_payload()
    del missing_name["name"]
    response = await client.post(
        "/api/v1/agents/minimal", json=missing_name, headers={"X-API-Key": "k1"}
    )
    assert response.status_code == 400

    bad_email = _minimal_payload(email="not-an-email")
    response = await client.post(
        "/api/v1/agents/minimal", json=bad_email, headers={"X-API-Key": "k2"}
    )
    assert response.status_code == 400


async def test_minimal_registration_duplicate_email_conflicts(client) -> None:
    await _register_minimal(client, api_key="dup-key-1")
    response = await client.post(
        "/api/v1/agents/minimal",
        json=_minimal_payload(name="Ada Clone"),
        headers={"X-API-Key": "dup-key-2"},
    )
    assert response.status_code == 409


async def test_minimal_registration_slug_uniqueness(client) -> None:
    first = await _register_minimal(
        client, _minimal_payload(name="Helper", email="one@example.com"), api_key="slug-1"
    )
    second = await _register_minimal(
        client, _minimal_payload(name="Helper", email="two@example.com"), api_key="slug-2"
    )
    assert first["directory_slug"] == "helper"
    assert second["directory_slug"] == "helper-2"


async def test_verify_email_success(client, monkeypatch) -> None:
    body = await _register_minimal(client, api_key="verify-key")
    agent_id = body["id"]

    _FakeChallengeClient.published = body["email_challenge"]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeChallengeClient)

    response = await client.post(
        f"/api/v1/agents/{agent_id}/verify-email", headers={"X-API-Key": "verify-key"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["email_verified"] is True

    detail = await client.get(f"/api/v1/agents/{agent_id}")
    assert detail.json()["email_verified"] is True


async def test_verify_email_wrong_token(client, monkeypatch) -> None:
    body = await _register_minimal(
        client, _minimal_payload(email="wrong@example.com"), api_key="verify-key-2"
    )

    _FakeChallengeClient.published = "not-the-challenge"
    monkeypatch.setattr(httpx, "AsyncClient", _FakeChallengeClient)

    response = await client.post(
        f"/api/v1/agents/{body['id']}/verify-email", headers={"X-API-Key": "verify-key-2"}
    )
    assert response.status_code == 422


async def test_verify_email_requires_owner_key(client, monkeypatch) -> None:
    body = await _register_minimal(
        client, _minimal_payload(email="owner@example.com"), api_key="owner-key"
    )

    _FakeChallengeClient.published = body["email_challenge"]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeChallengeClient)

    response = await client.post(
        f"/api/v1/agents/{body['id']}/verify-email", headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401


async def test_agents_json_feed(client) -> None:
    await _register_minimal(
        client, _minimal_payload(name="Feed One", email="one@example.com"), api_key="feed-1"
    )
    await _register_minimal(
        client, _minimal_payload(name="Feed Two", email="two@example.com"), api_key="feed-2"
    )

    response = await client.get("/agents.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    by_name = {entry["name"]: entry for entry in payload["agents"]}
    entry = by_name["Feed One"]
    assert entry["slug"] == "feed-one"
    assert entry["email"] == "one@example.com"
    assert entry["response_sla"] == "within 4 hours"
    assert entry["capabilities"] == ["email", "scheduling"]
    assert entry["verified_email"] is False
    assert "last_seen" in entry


async def test_home_page_renders_minimal_listings(client) -> None:
    await _register_minimal(client, api_key="home-key")
    response = await client.get("/")
    assert response.status_code == 200
    assert "ada@example.com" in response.text
    assert "within 4 hours" in response.text
