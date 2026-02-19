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


def _agent(url: str) -> Agent:
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
    assert attempts == ["/.well-known/agent-card.json", "/agents/demo"]
    assert agent.health_status == "healthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == now_utc


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
    assert attempts == ["/.well-known/agent-card.json", "/agents/demo", "/"]
    assert agent.health_status == "unhealthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == previous_last_healthy
