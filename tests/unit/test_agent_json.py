from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx

from agora.agent_json import verify_agent_json_manifest_with_indexing_metadata


@asynccontextmanager
async def _noop_pin_hostname_resolution(_hostname: str, _pinned_ip: str):
    yield


async def test_verify_agent_json_extracts_inline_commitments_metadata(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Inline Commitments Agent",
                    "url": "https://example.com/agents/demo",
                    "protocolVersion": "1.4.0",
                    "skills": [{"id": "echo", "name": "Echo"}],
                    "identity": {"oatr_issuer_id": "issuer-xyz"},
                    "commitments": {
                        "summary": "Commits to signed outputs",
                        "commitments": [{"id": "one"}, {"id": "two"}, {"id": "three"}],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.agent_json.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.agent_json.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified, oatr_issuer_id, commitments_count, commitments_summary = (
            await verify_agent_json_manifest_with_indexing_metadata(
                agent_url="https://example.com/agents/demo",
                client=client,
                allow_private_network_targets=False,
            )
        )

    assert verified is True
    assert oatr_issuer_id == "issuer-xyz"
    assert commitments_count == 3
    assert commitments_summary == "Commits to signed outputs"


async def test_verify_agent_json_skips_inline_commitments_for_non_v14(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Legacy Agent",
                    "url": "https://example.com/agents/legacy",
                    "protocolVersion": "0.3.0",
                    "skills": [{"id": "echo", "name": "Echo"}],
                    "commitments": {
                        "summary": "Legacy summary",
                        "commitments": [{"id": "one"}],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.agent_json.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.agent_json.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified, _oatr_issuer_id, commitments_count, commitments_summary = (
            await verify_agent_json_manifest_with_indexing_metadata(
                agent_url="https://example.com/agents/legacy",
                client=client,
                allow_private_network_targets=False,
            )
        )

    assert verified is True
    assert commitments_count is None
    assert commitments_summary is None


async def test_verify_agent_json_drops_metadata_when_domain_mismatch(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent.json":
            return httpx.Response(
                200,
                json={
                    "name": "Bad Origin Agent",
                    "url": "https://attacker.example/agents/demo",
                    "protocolVersion": "1.4.0",
                    "skills": [{"id": "echo", "name": "Echo"}],
                    "commitments": {
                        "summary": "Should not be trusted",
                        "commitments": [{"id": "one"}],
                    },
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.agent_json.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: SimpleNamespace(
            hostname="example.com",
            pinned_ip="93.184.216.34",
        ),
    )
    monkeypatch.setattr("agora.agent_json.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified, _oatr_issuer_id, commitments_count, commitments_summary = (
            await verify_agent_json_manifest_with_indexing_metadata(
                agent_url="https://example.com/agents/demo",
                client=client,
                allow_private_network_targets=False,
            )
        )

    assert verified is False
    assert commitments_count is None
    assert commitments_summary is None
