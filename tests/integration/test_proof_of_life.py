"""Integration tests for proof-of-life listing gating.

A listing goes public only after demonstrating the thing is real: a
reachable agent card (full A2A registrations) or a clicked email
verification link (minimal registrations). Pending listings exist and are
owner-manageable but invisible on every public surface.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

import agora.main as main_module
from agora.database import AsyncSessionLocal
from agora.main import _run_preflight_health_check as _real_preflight_health_check
from tests.integration.test_lifecycle import build_payload


@pytest.fixture
def capture_verification_email(monkeypatch):
    sent: list[dict] = []

    async def _fake_send(*, to_email: str, agent_name: str, verify_url: str) -> bool:
        sent.append({"to_email": to_email, "agent_name": agent_name, "verify_url": verify_url})
        return True

    monkeypatch.setattr(main_module, "_send_verification_email", _fake_send)
    return sent


def _stub_preflight(monkeypatch, *, status: str, detail: str = "stubbed") -> None:
    async def _check(_url: str) -> dict[str, str | None]:
        return {"status": status, "detail": detail}

    monkeypatch.setattr(main_module, "_run_preflight_health_check", _check)


def _minimal_payload(name: str, email: str) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "email": email,
        "response_sla": "within a day",
    }


async def _public_ids(client) -> set[str]:
    response = await client.get("/api/v1/agents")
    assert response.status_code == 200
    return {agent["id"] for agent in response.json()["agents"]}


# ---------------------------------------------------------------------------
# Full A2A path: agent-card reachability gates visibility
# ---------------------------------------------------------------------------


async def test_full_registration_passing_check_is_active_immediately(client) -> None:
    # The integration conftest stubs the preflight check to pass.
    response = await client.post(
        "/api/v1/agents",
        json=build_payload("Reachable Agent", "https://example.com/reachable"),
        headers={"X-API-Key": "reachable-key"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["listing_status"] == "active"
    assert body["pending_reason"] is None

    detail = await client.get(f"/api/v1/agents/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["health_status"] == "healthy"
    assert body["id"] in await _public_ids(client)


async def test_full_registration_failing_check_stays_pending_and_hidden(
    client, monkeypatch
) -> None:
    _stub_preflight(monkeypatch, status="fail", detail="connection refused")
    response = await client.post(
        "/api/v1/agents",
        json=build_payload("Unreachable Agent", "https://example.com/unreachable"),
        headers={"X-API-Key": "unreachable-key"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    agent_id = body["id"]
    assert body["listing_status"] == "pending"
    assert body["pending_reason"] == "connection refused"
    assert "retry-health-check" in body["message"]

    # Invisible everywhere public...
    assert agent_id not in await _public_ids(client)
    search = await client.get("/api/v1/agents/search", params={"q": "Unreachable"})
    assert search.status_code == 200
    assert all(a["id"] != agent_id for a in search.json()["agents"])
    assert (await client.get(f"/api/v1/agents/{agent_id}")).status_code == 404
    assert (await client.get(f"/agent/{agent_id}")).status_code == 404
    feed = await client.get("/agents.json")
    assert feed.status_code == 200
    assert feed.json()["count"] == 0
    home = await client.get("/")
    assert home.status_code == 200
    assert "Unreachable Agent" not in home.text

    # ...but the owner can still see and manage it.
    me = await client.get("/api/v1/me", headers={"X-API-Key": "unreachable-key"})
    assert me.status_code == 200
    assert me.json()["id"] == agent_id


async def test_retry_health_check_activates_listing(client, monkeypatch) -> None:
    _stub_preflight(monkeypatch, status="fail", detail="still down")
    body = (
        await client.post(
            "/api/v1/agents",
            json=build_payload("Flaky Agent", "https://example.com/flaky"),
            headers={"X-API-Key": "flaky-key"},
        )
    ).json()
    agent_id = body["id"]
    assert body["listing_status"] == "pending"
    retry_url = f"/api/v1/agents/{agent_id}/retry-health-check"

    bad_key = await client.post(retry_url, headers={"X-API-Key": "wrong-key"})
    assert bad_key.status_code == 401

    still_down = await client.post(retry_url, headers={"X-API-Key": "flaky-key"})
    assert still_down.status_code == 200
    assert still_down.json()["listing_status"] == "pending"
    assert still_down.json()["pending_reason"] == "still down"
    assert agent_id not in await _public_ids(client)

    _stub_preflight(monkeypatch, status="pass", detail="now reachable")
    recovered = await client.post(retry_url, headers={"X-API-Key": "flaky-key"})
    assert recovered.status_code == 200
    assert recovered.json()["listing_status"] == "active"
    assert recovered.json()["pending_reason"] is None

    assert agent_id in await _public_ids(client)
    assert (await client.get(f"/api/v1/agents/{agent_id}")).status_code == 200

    already = await client.post(retry_url, headers={"X-API-Key": "flaky-key"})
    assert already.json()["listing_status"] == "active"
    assert already.json()["message"] == "Listing is already active"


async def test_retry_health_check_rejects_minimal_listings(
    client, capture_verification_email
) -> None:
    body = (
        await client.post(
            "/api/v1/agents/minimal",
            json=_minimal_payload("Minimal Retry", "minimal-retry@example.com"),
            headers={"X-API-Key": "minimal-retry-key"},
        )
    ).json()
    response = await client.post(
        f"/api/v1/agents/{body['id']}/retry-health-check",
        headers={"X-API-Key": "minimal-retry-key"},
    )
    assert response.status_code == 409
    assert "email verification" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Minimal path: the verification click gates visibility
# ---------------------------------------------------------------------------


async def test_minimal_registration_pending_until_verified(
    client, capture_verification_email
) -> None:
    response = await client.post(
        "/api/v1/agents/minimal",
        json=_minimal_payload("Pending Minimal", "pending-minimal@example.com"),
        headers={"X-API-Key": "pending-minimal-key"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    agent_id = body["id"]
    assert body["listing_status"] == "pending"
    assert body["pending_reason"] == "Awaiting email verification"

    # Invisible everywhere public...
    assert (await client.get(f"/api/v1/agents/{agent_id}")).status_code == 404
    assert agent_id not in await _public_ids(client)
    feed = await client.get("/agents.json")
    assert feed.json()["count"] == 0
    home = await client.get("/")
    assert "pending-minimal@example.com" not in home.text

    # ...but the owner can still see and manage it.
    owner = await client.get(
        f"/api/v1/agents/{agent_id}/minimal", headers={"X-API-Key": "pending-minimal-key"}
    )
    assert owner.status_code == 200

    # Clicking the verification link publishes the listing.
    assert len(capture_verification_email) == 1
    verify_url = capture_verification_email[0]["verify_url"]
    token = verify_url.split("token=", 1)[1]
    verify = await client.get(f"/verify-email?token={token}")
    assert verify.status_code == 200

    assert (await client.get(f"/api/v1/agents/{agent_id}")).status_code == 200
    assert agent_id in await _public_ids(client)
    feed = await client.get("/agents.json")
    assert feed.json()["count"] == 1
    assert feed.json()["agents"][0]["verified_email"] is True


# ---------------------------------------------------------------------------
# Backfill migration: evidence-based, mechanical
# ---------------------------------------------------------------------------


def _alembic_config() -> Config:
    repo_root = Path(__file__).resolve().parents[2]
    return Config(str(repo_root / "alembic.ini"))


async def test_reputation_surfaces_hide_pending_listings(client, monkeypatch) -> None:
    """Reputation endpoints are public surfaces: pending listings 404 there."""
    _stub_preflight(monkeypatch, status="fail", detail="connection refused")
    response = await client.post(
        "/api/v1/agents",
        json=build_payload("Unreachable Agent", "https://example.com/unreachable"),
        headers={"X-API-Key": "unreachable-key"},
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]

    assert (await client.get(f"/api/v1/agents/{agent_id}/reliability")).status_code == 404
    assert (await client.get(f"/api/v1/agents/{agent_id}/incidents")).status_code == 404
    assert (await client.get(f"/api/v1/agents/{agent_id}/reputation")).status_code == 404
    assert (
        await client.post(
            f"/api/v1/agents/{agent_id}/reliability-reports",
            json={"interaction_date": "2026-09-28", "response_received": True},
            headers={"X-API-Key": "bogus-reporter"},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/agents/{agent_id}/incidents",
            json={
                "category": "other",
                "description": "nope",
                "outcome": "unresolved",
            },
            headers={"X-API-Key": "bogus-reporter"},
        )
    ).status_code == 404


async def test_a2a_badge_requires_fetched_card_proof(client, monkeypatch) -> None:
    """The A2A badge means we actually fetched a card, not just that a card
    URL was claimed. Backfilled-style rows (active, card URL, no health
    proof) do not get the badge."""
    fetched_card = {
        "protocolVersion": "0.3.0",
        "name": "Card URL Agent",
        "description": "Fetched card",
        "url": "https://card.example/agents/x",
        "version": "1.0.0",
        "skills": [{"id": "echo", "name": "Echo"}],
    }

    async def _fake_fetch(_url: str) -> dict:
        return fetched_card

    monkeypatch.setattr(main_module, "_fetch_agent_card_from_url", _fake_fetch)

    # Passing preflight (integration conftest default) -> active with proof.
    response = await client.post(
        "/api/v1/agents",
        json={"agent_card_url": "https://card.example/card", "name": "Card URL Agent"},
        headers={"X-API-Key": "card-key"},
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]
    page = await client.get(f"/agent/{agent_id}")
    assert page.status_code == 200
    assert "A2A Compatible" in page.text

    # Simulate a backfilled row: active + card URL but no health proof.
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                "UPDATE agents "
                "SET last_healthy_at = NULL, last_health_check = NULL "
                "WHERE id = :id"
            ),
            {"id": agent_id},
        )
        await session.commit()
    page = await client.get(f"/agent/{agent_id}")
    assert page.status_code == 200
    assert "A2A Compatible" not in page.text


async def test_backfill_migration_marks_only_unproven_listings_pending() -> None:
    cfg = _alembic_config()
    # Alembic's env.py drives migrations with asyncio.run(), which cannot
    # nest inside pytest's event loop — run the commands in a worker thread.
    await asyncio.to_thread(command.downgrade, cfg, "20260928_0024")
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO agents (name, agent_card, email_verified, health_status, last_healthy_at)
                    VALUES
                      ('verified-email', '{"name":"verified-email"}', true, 'unknown', NULL),
                      ('healthy', '{"name":"healthy"}', false, 'healthy', NULL),
                      ('was-healthy', '{"name":"was-healthy"}', false, 'unhealthy', now()),
                      ('unproven', '{"name":"unproven"}', false, 'unhealthy', NULL),
                      ('never-checked', '{"name":"never-checked"}', false, 'unknown', NULL)
                    """
                )
            )
            await session.commit()
        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    text("SELECT name, listing_status, pending_reason FROM agents ORDER BY name")
                )
            ).all()
    finally:
        # Always leave the test DB at head so other tests see the new columns.
        await asyncio.to_thread(command.upgrade, cfg, "head")

    by_name = {row[0]: (row[1], row[2]) for row in rows}
    assert by_name["verified-email"][0] == "active"
    assert by_name["healthy"][0] == "active"
    assert by_name["was-healthy"][0] == "active"
    assert by_name["unproven"] == (
        "pending",
        "Backfilled: never verified or health-checked",
    )
    assert by_name["never-checked"] == (
        "pending",
        "Backfilled: never verified or health-checked",
    )


# ---------------------------------------------------------------------------
# Bug regressions
# ---------------------------------------------------------------------------


async def test_email_change_before_initial_verification_still_publishes(
    client, capture_verification_email
) -> None:
    """Bug 1: confirming an email change before the initial verification click
    must publish the listing, not strand it verified-but-pending with no way
    out (resend says "already verified", health retry rejects minimal
    listings)."""
    response = await client.post(
        "/api/v1/agents/minimal",
        json=_minimal_payload("Email Changer", "changer-old@example.com"),
        headers={"X-API-Key": "changer-key"},
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]
    assert response.json()["listing_status"] == "pending"

    # Owner corrects the address before clicking the initial verification link.
    patch = await client.patch(
        f"/api/v1/agents/{agent_id}/minimal",
        json={"email": "changer-new@example.com"},
        headers={"X-API-Key": "changer-key"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["pending_email"] == "changer-new@example.com"

    # The second captured email is the change-confirmation link.
    assert len(capture_verification_email) == 2
    verify_url = capture_verification_email[1]["verify_url"]
    token = verify_url.split("token=")[1]
    verify = await client.get(f"/verify-email?token={token}")
    assert verify.status_code == 200

    # Verified AND public — no dead end.
    assert agent_id in await _public_ids(client)
    assert (await client.get(f"/api/v1/agents/{agent_id}")).status_code == 200

    owner = await client.get(
        f"/api/v1/agents/{agent_id}/minimal", headers={"X-API-Key": "changer-key"}
    )
    assert owner.status_code == 200
    assert owner.json()["listing_status"] == "active"
    assert owner.json()["pending_reason"] is None
    assert owner.json()["email_verified"] is True
    assert owner.json()["email"] == "changer-new@example.com"


async def test_registration_with_card_only_at_agent_json_goes_active(
    client, monkeypatch
) -> None:
    """Bug 2: registration fetches the card from /.well-known/agent.json, so
    the proof-of-life probe must cover the same location. A card served ONLY
    there must land active, not pending."""
    host = "wellknown-card.example.com"
    card = {
        "protocolVersion": "0.3.0",
        "name": "Well-Known Agent",
        "description": "Serves its card only at /.well-known/agent.json",
        "url": f"https://{host}/",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [{"id": "echo", "name": "Echo"}],
    }

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload
            self.headers = {"content-type": "application/json"}

        def json(self) -> dict:
            if self._payload is None:
                raise ValueError("no JSON body")
            return self._payload

    real_get = httpx.AsyncClient.get

    async def _fake_get(self, url, **kwargs):
        url_str = str(url)
        if host in url_str:
            if url_str.endswith("/.well-known/agent.json"):
                return _FakeResponse(200, card)
            return _FakeResponse(404)
        return await real_get(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    # Restore the real proof-of-life check (the integration conftest stubs it).
    monkeypatch.setattr(
        main_module, "_run_preflight_health_check", _real_preflight_health_check
    )

    response = await client.post(
        "/api/v1/agents",
        json={"agent_card_url": f"https://{host}", "name": "Well-Known Agent"},
        headers={"X-API-Key": "wellknown-key"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["listing_status"] == "active", body["pending_reason"]
    assert body["pending_reason"] is None
    assert body["id"] in await _public_ids(client)


async def test_registration_with_card_only_at_path_relative_well_known_goes_active(
    client, monkeypatch
) -> None:
    """Bug 2 remainder: registration resolves the card path-relative to
    agent_card_url (urljoin(f"{base}/", ".well-known/agent.json")). A card
    served ONLY at that path-relative location must land active — the
    proof-of-life probe has to cover the same location registration fetched,
    or a valid registration passes validation and then fails every health
    check, stranding the listing pending forever."""
    host = "path-card.example.com"
    card = {
        "protocolVersion": "0.3.0",
        "name": "Path Card Agent",
        "description": "Serves its card only under a path-relative well-known URL",
        "url": f"https://{host}/agents/demo",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [{"id": "echo", "name": "Echo"}],
    }

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload
            self.headers = {"content-type": "application/json"}

        def json(self) -> dict:
            if self._payload is None:
                raise ValueError("no JSON body")
            return self._payload

    real_get = httpx.AsyncClient.get

    async def _fake_get(self, url, **kwargs):
        url_str = str(url)
        if host in url_str:
            # The ONLY place this agent serves its card: exactly where
            # registration resolves it relative to agent_card_url.
            if url_str == f"https://{host}/agents/demo/.well-known/agent.json":
                return _FakeResponse(200, card)
            return _FakeResponse(404)
        return await real_get(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    # Restore the real proof-of-life check (the integration conftest stubs it).
    monkeypatch.setattr(
        main_module, "_run_preflight_health_check", _real_preflight_health_check
    )

    response = await client.post(
        "/api/v1/agents",
        json={"agent_card_url": f"https://{host}/agents/demo", "name": "Path Card Agent"},
        headers={"X-API-Key": "pathcard-key"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["listing_status"] == "active", body["pending_reason"]
    assert body["pending_reason"] is None
    assert body["id"] in await _public_ids(client)
