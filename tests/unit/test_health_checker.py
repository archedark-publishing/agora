from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from agora.health_checker import (
    _check_single_agent,
    build_agent_card_probe_url,
    build_agent_card_probe_urls,
)
from agora.models import Agent


def _valid_card(url: str, *, protocol_version: str = "0.3.0") -> dict[str, object]:
    return {
        "protocolVersion": protocol_version,
        "name": "Health Test Agent",
        "description": "Health checker unit test card.",
        "url": url,
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [{"id": "health-test", "name": "Health Test"}],
    }


def _agent(
    url: str,
    *,
    econ_id: str | None = None,
    commitments_url: str | None = None,
    did: str | None = None,
    did_verified: bool = False,
) -> Agent:
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
        did=did,
        did_verified=did_verified,
        agent_json_verified=False,
        commitments_url=commitments_url,
        commitment_verified=False,
        erc8004_verified=False,
    )


@asynccontextmanager
async def _noop_pin_hostname_resolution(_hostname: str, _pinned_ip: str):
    yield


def _patch_outbound_safety(monkeypatch) -> None:
    """Make outbound URL-safety checks hermetic for every module in a sweep.

    ``_check_single_agent`` fans out to ERC-8004 discovery and agent.json
    manifest verification, and each of ``agora.health_checker``,
    ``agora.erc8004`` and ``agora.agent_json`` imports its own
    ``assert_url_safe_for_outbound`` / ``pin_hostname_resolution`` binding.
    Patching only one module leaves the tests depending on real DNS for
    example.com resolving to a public IP — in sandboxes where it resolves
    privately the unpatched fetches silently never happen and attempt logs
    (and verification outcomes) diverge.
    """

    def _safe_target(_url: str, allow_private: bool = False) -> SimpleNamespace:
        return SimpleNamespace(hostname="example.com", pinned_ip="93.184.216.34")

    for _module in ("agora.health_checker", "agora.erc8004", "agora.agent_json"):
        monkeypatch.setattr(f"{_module}.assert_url_safe_for_outbound", _safe_target)
        monkeypatch.setattr(f"{_module}.pin_hostname_resolution", _noop_pin_hostname_resolution)


def test_build_agent_card_probe_urls_orders_and_dedupes() -> None:
    assert build_agent_card_probe_urls("https://example.com/agents/demo?x=1#section") == [
        "https://example.com/.well-known/agent-card.json",
        "https://example.com/.well-known/agent.json",
        "https://example.com/agents/demo/.well-known/agent-card.json",
        "https://example.com/agents/demo/.well-known/agent.json",
        "https://example.com/agents/demo",
        "https://example.com/",
    ]
    assert build_agent_card_probe_urls("https://example.com/") == [
        "https://example.com/.well-known/agent-card.json",
        "https://example.com/.well-known/agent.json",
        "https://example.com/",
    ]


def test_build_agent_card_probe_urls_includes_path_relative_well_known() -> None:
    """Registration resolves the card path-relative to agent_card_url
    (urljoin(f"{base}/", ".well-known/agent.json")), so the probe list must
    include the same path-relative locations — otherwise a card served only
    under a path passes registration validation but fails every health
    check and the listing is stranded pending."""
    urls = build_agent_card_probe_urls("https://example.com/agents/demo")
    assert urls[2] == "https://example.com/agents/demo/.well-known/agent-card.json"
    assert urls[3] == "https://example.com/agents/demo/.well-known/agent.json"


def test_build_agent_card_probe_urls_divergent_card_url_comes_first() -> None:
    """When the card was fetched from a different URL than the card's own
    `url` field (e.g. card fetched at /agents/demo/.well-known/agent.json but
    declaring "url": "https://example.com/rpc"), the proven fetch location
    must be probed first -- otherwise registration validates the card and the
    health check never looks where the card actually lives."""
    urls = build_agent_card_probe_urls(
        "https://example.com/rpc", "https://example.com/agents/demo"
    )
    assert urls == [
        # Proven fetch location (agent_card_url) first.
        "https://example.com/.well-known/agent-card.json",
        "https://example.com/.well-known/agent.json",
        "https://example.com/agents/demo/.well-known/agent-card.json",
        "https://example.com/agents/demo/.well-known/agent.json",
        "https://example.com/agents/demo",
        "https://example.com/",
        # Card's self-asserted endpoint second.
        "https://example.com/rpc/.well-known/agent-card.json",
        "https://example.com/rpc/.well-known/agent.json",
        "https://example.com/rpc",
    ]


def test_build_agent_card_probe_urls_identical_urls_unchanged() -> None:
    """Identical (or absent) card URL collapses to exactly the single-base
    list -- no behavior change for the common case."""
    single = build_agent_card_probe_urls("https://example.com/agents/demo")
    assert build_agent_card_probe_urls(
        "https://example.com/agents/demo", "https://example.com/agents/demo"
    ) == single
    assert build_agent_card_probe_urls("https://example.com/agents/demo", None) == single
    assert build_agent_card_probe_url(
        "https://example.com/rpc", "https://example.com/agents/demo"
    ) == "https://example.com/.well-known/agent-card.json"


async def test_check_single_agent_uses_fallback_when_well_known_fails(monkeypatch) -> None:
    attempts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(404, request=request)
        if request.url.path == "/agents/demo":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
    assert attempts == [
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/agents/demo/.well-known/agent-card.json",
        "/agents/demo/.well-known/agent.json",
        "/agents/demo",
        "/.well-known/agent-registration.json",
        "/.well-known/agent.json",
    ]
    assert agent.health_status == "healthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == now_utc
    assert agent.protocol_version == "0.3.0"
    assert agent.erc8004_verified is False


async def test_check_single_agent_refreshes_protocol_version_from_fetched_card(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(
                200,
                json=_valid_card("https://example.com/agents/demo", protocol_version="1.0.0"),
                request=request,
            )
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

    agent = _agent("https://example.com/agents/demo")
    agent.protocol_version = "0.3.0"
    now_utc = datetime.now(tz=timezone.utc)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )

    assert healthy is True
    assert agent.protocol_version == "1.0.0"


async def test_check_single_agent_marks_unhealthy_when_all_probes_fail(monkeypatch) -> None:
    attempts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
        "/.well-known/agent.json",
        "/agents/demo/.well-known/agent-card.json",
        "/agents/demo/.well-known/agent.json",
        "/agents/demo",
        "/",
        "/.well-known/agent-registration.json",
        "/.well-known/agent.json",
    ]
    assert agent.health_status == "unhealthy"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at == previous_last_healthy
    assert agent.protocol_version is None
    assert agent.erc8004_verified is False


async def test_check_single_agent_keeps_unknown_when_never_verified(monkeypatch) -> None:
    """A listing that never passed proof-of-life (e.g. a minimal
    email-verified listing with an informational URL) must stay "unknown"
    when probes fail — "unhealthy" means regression from a verified state."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

    agent = _agent("https://example.com/")
    assert agent.last_healthy_at is None
    now_utc = datetime.now(tz=timezone.utc)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )

    assert healthy is False
    assert agent.health_status == "unknown"
    assert agent.last_health_check == now_utc
    assert agent.last_healthy_at is None
    assert agent.protocol_version is None


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

    _patch_outbound_safety(monkeypatch)

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


async def test_check_single_agent_recomputes_commitment_verification(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        return httpx.Response(404, request=request)

    async def _fake_verify_commitments_document(**kwargs) -> bool:
        return bool(kwargs["did_verified"]) and kwargs["did"] == "did:web:commitments.example"

    _patch_outbound_safety(monkeypatch)
    monkeypatch.setattr("agora.health_checker.verify_commitments_document", _fake_verify_commitments_document)

    agent = _agent(
        "https://example.com/agents/demo",
        commitments_url="https://commitments.example/.well-known/agent-commitments.json",
        did="did:web:commitments.example",
        did_verified=True,
    )
    now_utc = datetime.now(tz=timezone.utc)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        healthy = await _check_single_agent(
            agent,
            client,
            now_utc,
            allow_private_network_targets=False,
        )

    assert healthy is True
    assert agent.commitment_verified is True


async def test_check_single_agent_verifies_agent_json_manifest(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Health Test Agent",
                    "url": "https://example.com/agents/demo",
                    "protocolVersion": "1.4.0",
                    "skills": [{"name": "health-check"}],
                    "identity": {"oatr_issuer_id": "issuer-123"},
                    "commitments": {
                        "summary": "Commits to deterministic outputs",
                        "commitments": [{"id": "c1"}, {"id": "c2"}],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
    assert agent.agent_json_verified is True
    assert agent.oatr_issuer_id == "issuer-123"
    assert agent.commitments_count == 2
    assert agent.commitments_summary == "Commits to deterministic outputs"


async def test_check_single_agent_fails_agent_json_domain_mismatch(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Health Test Agent",
                    "url": "https://attacker.example/agents/demo",
                    "protocolVersion": "1.4.0",
                    "skills": [{"name": "health-check"}],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
    assert agent.agent_json_verified is False
    assert agent.commitments_count is None
    assert agent.commitments_summary is None


async def test_check_single_agent_fails_agent_json_did_mismatch(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Health Test Agent",
                    "url": "https://example.com/agents/demo",
                    "protocolVersion": "1.4.0",
                    "skills": [{"name": "health-check"}],
                    "identity": {"did": "did:web:example.com"},
                },
                request=request,
            )
        if request.url.path == "/.well-known/did.json":
            return httpx.Response(
                200,
                json={"id": "did:web:someone-else.example"},
                request=request,
            )
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
    assert agent.agent_json_verified is False
    assert agent.commitments_count is None
    assert agent.commitments_summary is None


async def test_check_single_agent_skips_when_agent_json_missing(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=_valid_card("https://example.com/agents/demo"), request=request)
        return httpx.Response(404, request=request)

    _patch_outbound_safety(monkeypatch)

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
    assert agent.agent_json_verified is False
    assert agent.commitments_count is None
    assert agent.commitments_summary is None
