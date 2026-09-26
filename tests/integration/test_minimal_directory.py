"""Integration tests for the Agora v2 minimal directory endpoints."""

from __future__ import annotations

import pytest

import agora.main as main_module


@pytest.fixture
def capture_verification_email(monkeypatch):
    """Capture outbound verification emails instead of sending them."""
    sent: list[dict] = []

    async def _fake_send(*, to_email: str, agent_name: str, verify_url: str) -> bool:
        sent.append(
            {"to_email": to_email, "agent_name": agent_name, "verify_url": verify_url}
        )
        return True

    monkeypatch.setattr(
        main_module, "_send_verification_email", _fake_send
    )
    return sent


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


def _token_from_url(verify_url: str) -> str:
    assert "token=" in verify_url
    return verify_url.split("token=", 1)[1]


async def test_minimal_registration_happy_path(client, capture_verification_email) -> None:
    body = await _register_minimal(client)
    assert body["name"] == "Ada"
    assert body["directory_slug"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["email_verified"] is False
    assert body["verification_email_sent"] is True
    assert "email_challenge" not in body

    assert len(capture_verification_email) == 1
    sent = capture_verification_email[0]
    assert sent["to_email"] == "ada@example.com"
    assert sent["agent_name"] == "Ada"
    assert sent["verify_url"].startswith("https://the-agora.dev/verify-email?token=")

    detail = await client.get(f"/api/v1/agents/{body['id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["email"] == "ada@example.com"
    assert payload["response_sla"] == "within 4 hours"
    assert payload["email_verified"] is False
    assert payload["directory_slug"] == "ada"
    assert "url" not in payload  # email-only listings have no URL


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


async def test_verify_email_link_success(client, capture_verification_email) -> None:
    body = await _register_minimal(client, api_key="verify-key")
    token = _token_from_url(capture_verification_email[0]["verify_url"])

    response = await client.get(f"/verify-email?token={token}")
    assert response.status_code == 200, response.text
    assert "Email verified" in response.text

    detail = await client.get(f"/api/v1/agents/{body['id']}")
    assert detail.json()["email_verified"] is True


async def test_verify_email_link_already_verified(client, capture_verification_email) -> None:
    await _register_minimal(client, api_key="verify-twice-key")
    token = _token_from_url(capture_verification_email[0]["verify_url"])

    first = await client.get(f"/verify-email?token={token}")
    assert first.status_code == 200

    second = await client.get(f"/verify-email?token={token}")
    assert second.status_code == 200
    assert "Already verified" in second.text


async def test_verify_email_link_tampered_token(client) -> None:
    response = await client.get("/verify-email?token=tampered.payload.here")
    assert response.status_code == 400
    assert "invalid or expired" in response.text


async def test_verify_email_link_missing_token(client) -> None:
    response = await client.get("/verify-email")
    assert response.status_code == 400


async def test_verify_email_link_expired(
    client, capture_verification_email, monkeypatch
) -> None:
    monkeypatch.setattr(
        main_module.settings, "email_verification_ttl_hours", -1
    )
    await _register_minimal(client, api_key="expired-key")
    token = _token_from_url(capture_verification_email[0]["verify_url"])

    response = await client.get(f"/verify-email?token={token}")
    assert response.status_code == 400
    assert "invalid or expired" in response.text


async def test_resend_verification_email(client, capture_verification_email) -> None:
    body = await _register_minimal(client, api_key="resend-key")
    assert len(capture_verification_email) == 1

    response = await client.post(
        f"/api/v1/agents/{body['id']}/verify-email/resend",
        headers={"X-API-Key": "resend-key"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["verification_email_sent"] is True
    assert len(capture_verification_email) == 2


async def test_resend_verification_email_requires_owner_key(
    client, capture_verification_email
) -> None:
    body = await _register_minimal(client, api_key="resend-owner-key")

    response = await client.post(
        f"/api/v1/agents/{body['id']}/verify-email/resend",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401
    assert len(capture_verification_email) == 1


async def test_resend_verification_email_already_verified(
    client, capture_verification_email
) -> None:
    body = await _register_minimal(client, api_key="resend-done-key")
    token = _token_from_url(capture_verification_email[0]["verify_url"])
    verify = await client.get(f"/verify-email?token={token}")
    assert verify.status_code == 200

    response = await client.post(
        f"/api/v1/agents/{body['id']}/verify-email/resend",
        headers={"X-API-Key": "resend-done-key"},
    )
    assert response.status_code == 200
    assert response.json()["email_verified"] is True
    # No new email goes out for an already-verified listing.
    assert len(capture_verification_email) == 1


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


async def test_email_only_listing_shows_email_only_badge(
    client, capture_verification_email
) -> None:
    email_only = await _register_minimal(
        client,
        payload=_minimal_payload(
            name="Email Only Badge Agent", email="email-only-badge@example.com"
        ),
        api_key="email-only-badge-key",
    )
    url_payload = _minimal_payload(
        name="URL Badge Agent", email="url-badge@example.com"
    )
    url_payload["url"] = "https://example.com/url-badge-agent"
    await _register_minimal(
        client, payload=url_payload, api_key="url-badge-key"
    )

    response = await client.get("/")
    assert response.status_code == 200
    assert "Email Only Badge Agent" in response.text
    assert "URL Badge Agent" in response.text
    # Email-only listings have no endpoint to probe, so the badge explains
    # that instead of the misleading "Unknown".
    assert '<span class="badge badge-email"' in response.text
    assert "Email only" in response.text
    # A listing WITH a URL whose health was never checked still shows Unknown.
    assert '<span class="badge badge-unknown">Unknown</span>' in response.text

    detail = await client.get(f"/agent/{email_only['id']}")
    assert detail.status_code == 200
    assert "Email only" in detail.text
