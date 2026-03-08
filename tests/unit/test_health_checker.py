from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from agora.health_checker import _check_single_agent, build_agent_card_probe_urls
from agora.models import Agent


def _valid_card(url: str) -> dict[str, object]:
    return {
        "protocolVersion": "0.3.0",
        "name": "Health Test Agent",
        "description": "Health checker unit test card.",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "health-test", "name": "Health Test"}],
    }


def _agent(url: str, *, econ_id: str | None = None) -> Agent:
    return Agent(
        name="Health Test Agent",
        description="Health checker unit test agent.",
        url=url,
        version="1.0.0",
        protocol_version="0.3.0",
        agent_card=_valid_card(url),
        skills=["health-test"],
        capabilities=["streaming"],
        tags=[],
        input_modes=[],
        output_modes=[],
        owner_key_hash=None,
        health_status="unknown",
        econ_id=econ_id,
        erc8004_verified=False,
    )


@asynccontextmanager
async def _noop_pin_hostname_resolution(_hostname: str, _pinned_ip: str):
    yield


def test_build_agent_card_probe_urls_orders_and_dedupes() -> None:
    assert build_agent_card_probe_urls("https://example.com/agents/demo?x=1#section") == [
        "https://example.com/.well-known/agent-card.json",
        "https://example.com/agents/demo",
        "https://example.com/",
    ]
    assert build_agent_card_probe_urls("https://example.com/") == [
        "https://example.com/.well-known/agent-card.json",
        "https://example.com/",
    ]


async def test_check_single_agent_uses_fallback_when_well_known_fails(monkeypatch) -> None:
    attempts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(404, request=request)
        if request.url.path == "/agents/demo":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.health_checker.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.health_checker.pin_hostname_resolution", _noop_pin_hostname_resolution)

    agent = _agent("https://example.com/agents/demo")
    now_utc = datetime.now(tz=timezone.utc)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )

    assert healthy is True
    assert attempts == ["/.well-known/agent-card.json", "/agents/demo", "/.well-known/agent-registration.json"]
    assert agent.health_status == "healthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == now_utc
    assert agent.erc8004_verified is False


async def test_check_single_agent_marks_unhealthy_when_all_probes_fail(monkeypatch) -> None:
    attempts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.health_checker.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.health_checker.pin_hostname_resolution", _noop_pin_hostname_resolution)

    agent = _agent("https://example.com/agents/demo")
    previous_last_healthy = datetime.now(tz=timezone.utc)
    agent.last_healthy_at = previous_last_healthy
    now_utc = datetime.now(tz=timezone.utc)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )

    assert healthy is False
    assert attempts == [
        "/.well-known/agent-card.json",
        "/agents/demo",
        "/",
        "/.well-known/agent-registration.json",
    ]
    assert agent.health_status == "unhealthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == previous_last_healthy
    assert agent.erc8004_verified is False


async def test_check_single_agent_verifies_or_populates_econ_id_from_erc8004_registration(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        if request.url.path == "/.well-known/agent-registration.json":
            return httpx.Response(
                200,
                json={
                    "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
                    "registrations": [
                        {
                            "agentRegistry": "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                            "agentId": 22,
                        }
                    ],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.health_checker.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.health_checker.pin_hostname_resolution", _noop_pin_hostname_resolution)

    now_utc = datetime.now(tz=timezone.utc)

    # Existing econ_id matches discovered registration
    matching_agent = _agent(
        "https://example.com/agents/demo",
        econ_id="eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e:22",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            matching_agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )
    assert healthy is True
    assert matching_agent.erc8004_verified is True
    assert matching_agent.econ_id == "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e:22"

    # Missing econ_id is auto-populated
    missing_agent = _agent("https://example.com/agents/demo")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            missing_agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )
    assert healthy is True
    assert missing_agent.erc8004_verified is True
    assert missing_agent.econ_id == "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e:22"
