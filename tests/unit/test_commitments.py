from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import base58
import httpx
from nacl.signing import SigningKey

from agora.commitments import verify_commitments_document


@asynccontextmanager
async def _noop_pin_hostname_resolution(_hostname: str, _pinned_ip: str):
    yield


def _safe_target(url: str, *, allow_private: bool = False) -> SimpleNamespace:
    del allow_private
    return SimpleNamespace(
        hostname=urlsplit(url).hostname or "agent.example",
        pinned_ip="93.184.216.34",
    )


async def test_verify_commitments_document_succeeds_for_valid_signed_payload(monkeypatch) -> None:
    did = "did:web:agent.example"
    commitments_url = "https://agent.example/.well-known/agent-commitments.json"

    signing_key = SigningKey.generate()
    public_key_multibase = "z" + base58.b58encode(signing_key.verify_key.encode()).decode("ascii")

    canonical_payload = {
        "agent_did": did,
        "invariants": [
            {
                "id": "no-undisclosed-data-retention",
                "description": "No retention beyond agreed SLA windows.",
            }
        ],
    }
    canonical_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature_hex = signing_key.sign(canonical_bytes).signature.hex()

    commitments_payload = {
        **canonical_payload,
        "signature": signature_hex,
    }

    did_document = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#owner",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": public_key_multibase,
            }
        ],
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-commitments.json":
            return httpx.Response(200, json=commitments_payload, request=request)
        if request.url.path == "/.well-known/did.json":
            return httpx.Response(200, json=did_document, request=request)
        return httpx.Response(404, request=request)

    monkeypatch.setattr("agora.commitments.assert_url_safe_for_outbound", _safe_target)
    monkeypatch.setattr("agora.commitments.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified = await verify_commitments_document(
            commitments_url=commitments_url,
            did=did,
            did_verified=True,
            allow_private_network_targets=False,
            client=client,
        )

    assert verified is True


async def test_verify_commitments_document_returns_false_for_invalid_signature(monkeypatch) -> None:
    did = "did:web:agent.example"
    commitments_url = "https://agent.example/.well-known/agent-commitments.json"

    signing_key = SigningKey.generate()
    public_key_multibase = "z" + base58.b58encode(signing_key.verify_key.encode()).decode("ascii")

    canonical_payload = {
        "agent_did": did,
        "invariants": [{"id": "safe-output-only"}],
    }
    canonical_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature_hex = signing_key.sign(canonical_bytes).signature.hex()

    # Tamper the payload after signing.
    commitments_payload = {
        "agent_did": did,
        "invariants": [{"id": "tampered-after-signing"}],
        "signature": signature_hex,
    }

    did_document = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#owner",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": public_key_multibase,
            }
        ],
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-commitments.json":
            return httpx.Response(200, json=commitments_payload, request=request)
        if request.url.path == "/.well-known/did.json":
            return httpx.Response(200, json=did_document, request=request)
        return httpx.Response(404, request=request)

    monkeypatch.setattr("agora.commitments.assert_url_safe_for_outbound", _safe_target)
    monkeypatch.setattr("agora.commitments.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified = await verify_commitments_document(
            commitments_url=commitments_url,
            did=did,
            did_verified=True,
            allow_private_network_targets=False,
            client=client,
        )

    assert verified is False


async def test_verify_commitments_document_requires_verified_did(monkeypatch) -> None:
    attempts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        return httpx.Response(500, request=request)

    monkeypatch.setattr("agora.commitments.assert_url_safe_for_outbound", _safe_target)
    monkeypatch.setattr("agora.commitments.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified = await verify_commitments_document(
            commitments_url="https://agent.example/.well-known/agent-commitments.json",
            did="did:web:agent.example",
            did_verified=False,
            allow_private_network_targets=False,
            client=client,
        )

    assert verified is False
    assert attempts == []


async def test_verify_commitments_document_handles_multicodec_prefixed_key(monkeypatch) -> None:
    """Ed25519VerificationKey2020 publicKeyMultibase values are base58btc-encoded
    with a 2-byte multicodec prefix (0xed 0x01) prepended to the 32-byte raw key,
    producing a 34-byte decoded value. extract_ed25519_public_key_bytes must strip
    the prefix before the len == 32 check or verification silently fails."""
    did = "did:web:agent.example"
    commitments_url = "https://agent.example/.well-known/agent-commitments.json"

    signing_key = SigningKey.generate()
    # Spec-compliant Ed25519VerificationKey2020: prepend 0xed 0x01 multicodec prefix.
    multicodec_prefixed = b"\xed\x01" + signing_key.verify_key.encode()
    public_key_multibase = "z" + base58.b58encode(multicodec_prefixed).decode("ascii")

    canonical_payload = {
        "agent_did": did,
        "invariants": [{"id": "safe-output-only"}],
    }
    canonical_bytes = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature_hex = signing_key.sign(canonical_bytes).signature.hex()

    commitments_payload = {
        **canonical_payload,
        "signature": signature_hex,
    }

    did_document = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#owner",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": public_key_multibase,
            }
        ],
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-commitments.json":
            return httpx.Response(200, json=commitments_payload, request=request)
        if request.url.path == "/.well-known/did.json":
            return httpx.Response(200, json=did_document, request=request)
        return httpx.Response(404, request=request)

    monkeypatch.setattr("agora.commitments.assert_url_safe_for_outbound", _safe_target)
    monkeypatch.setattr("agora.commitments.pin_hostname_resolution", _noop_pin_hostname_resolution)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        verified = await verify_commitments_document(
            commitments_url=commitments_url,
            did=did,
            did_verified=True,
            allow_private_network_targets=False,
            client=client,
        )

    assert verified is True
