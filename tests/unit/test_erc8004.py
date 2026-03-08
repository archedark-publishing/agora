from __future__ import annotations

import httpx

from agora.erc8004 import (
    build_registration_url,
    discover_erc8004_registration_econ_id,
    resolve_erc8004_verification,
)


def test_build_registration_url_uses_endpoint_domain() -> None:
    assert (
        build_registration_url("https://example.com/agents/demo?x=1")
        == "https://example.com/.well-known/agent-registration.json"
    )


async def test_discover_erc8004_registration_econ_id_parses_first_valid_registration(monkeypatch) -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-registration.json":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
                    "registrations": [
                        {"agentRegistry": "", "agentId": 22},
                        {
                            "agentRegistry": "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                            "agentId": 22,
                        },
                    ],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "agora.erc8004.assert_url_safe_for_outbound",
        lambda _url, allow_private=False: type("Target", (), {"hostname": "example.com", "pinned_ip": "93.184.216.34"})(),
    )

    # keep pinning simple for unit test
    class _Pin:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("agora.erc8004.pin_hostname_resolution", lambda *_args, **_kwargs: _Pin())

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        econ_id = await discover_erc8004_registration_econ_id(
            "https://example.com/agents/demo",
            client=client,
            allow_private_network_targets=False,
        )

    assert econ_id == "eip155:1:0x742d35Cc6634C0532925a3b844Bc454e4438f44e:22"


def test_resolve_erc8004_verification() -> None:
    missing = resolve_erc8004_verification(None, "eip155:1:0xabc:1")
    assert missing.econ_id == "eip155:1:0xabc:1"
    assert missing.verified is True

    mismatch = resolve_erc8004_verification("eip155:1:0xabc:2", "eip155:1:0xabc:1")
    assert mismatch.econ_id == "eip155:1:0xabc:2"
    assert mismatch.verified is False

    unavailable = resolve_erc8004_verification("eip155:1:0xabc:2", None)
    assert unavailable.econ_id == "eip155:1:0xabc:2"
    assert unavailable.verified is False
