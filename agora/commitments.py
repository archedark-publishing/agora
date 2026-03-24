"""Commitment declaration verification helpers."""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote

import base58
import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from agora.url_safety import URLSafetyError, assert_url_safe_for_outbound, pin_hostname_resolution


def _did_web_document_url(did: str) -> str:
    did_prefix = "did:web:"
    if not did.startswith(did_prefix):
        raise ValueError("DID method is not did:web")

    method_specific_id = did[len(did_prefix) :]
    if not method_specific_id:
        raise ValueError("Invalid did:web format")

    encoded_host = method_specific_id.split(":", maxsplit=1)[0]
    host = unquote(encoded_host).strip()
    if not host or "/" in host:
        raise ValueError("Invalid did:web format")

    return f"https://{host}/.well-known/did.json"


def _normalize_required_commitments_fields(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    agent_did = payload.get("agent_did")
    invariants = payload.get("invariants")
    signature = payload.get("signature")
    if not isinstance(agent_did, str) or not agent_did.strip():
        return None
    if not isinstance(invariants, list):
        return None
    if not isinstance(signature, str) or not signature.strip():
        return None

    return payload


def _canonical_commitments_payload(payload: dict[str, Any]) -> bytes:
    canonical_payload = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _decode_multibase_base58(value: str) -> bytes | None:
    if not value.startswith("z"):
        return None
    try:
        return base58.b58decode(value[1:])
    except ValueError:
        return None


def _decode_signature(signature: str) -> bytes | None:
    normalized = signature.strip()
    if not normalized:
        return None

    multibase = _decode_multibase_base58(normalized)
    if multibase is not None:
        return multibase

    try:
        return bytes.fromhex(normalized.removeprefix("0x"))
    except ValueError:
        pass

    candidates = [normalized, normalized + "=" * (-len(normalized) % 4)]
    for candidate in candidates:
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                return decoder(candidate)
            except (ValueError, TypeError):
                continue

    return None


def _extract_ed25519_public_key_bytes(did_document: dict[str, Any], did: str) -> bytes | None:
    verification_methods = did_document.get("verificationMethod")
    if not isinstance(verification_methods, list):
        return None

    for method in verification_methods:
        if not isinstance(method, dict):
            continue

        controller = method.get("controller")
        if isinstance(controller, str) and controller and controller != did:
            continue

        method_type = method.get("type")
        if isinstance(method_type, str) and "ed25519" not in method_type.lower():
            continue

        public_key_multibase = method.get("publicKeyMultibase")
        if isinstance(public_key_multibase, str):
            decoded = _decode_multibase_base58(public_key_multibase)
            if decoded is not None and len(decoded) == 32:
                return decoded

        public_key_base58 = method.get("publicKeyBase58")
        if isinstance(public_key_base58, str):
            try:
                decoded = base58.b58decode(public_key_base58)
            except ValueError:
                continue
            if len(decoded) == 32:
                return decoded

    return None


async def _fetch_json_document(
    url: str,
    *,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> dict[str, Any] | None:
    try:
        safe_target = assert_url_safe_for_outbound(
            url,
            allow_private=allow_private_network_targets,
        )
        async with pin_hostname_resolution(safe_target.hostname, safe_target.pinned_ip):
            response = await client.get(url, follow_redirects=False)
    except (URLSafetyError, httpx.HTTPError):
        return None

    if response.status_code != httpx.codes.OK:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


async def _fetch_did_document(
    did: str,
    *,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> dict[str, Any] | None:
    try:
        did_document_url = _did_web_document_url(did)
    except ValueError:
        return None

    did_document = await _fetch_json_document(
        did_document_url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    if did_document is None:
        return None

    if did_document.get("id") != did:
        return None

    return did_document


@asynccontextmanager
async def _client_context(
    *,
    client: httpx.AsyncClient | None,
    timeout_seconds: int,
):
    if client is not None:
        yield client
        return

    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as generated_client:
        yield generated_client


async def verify_commitments_document(
    *,
    commitments_url: str | None,
    did: str | None,
    did_verified: bool,
    allow_private_network_targets: bool,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: int = 10,
) -> bool:
    """Verify an agent commitments document against the DID-resolved Ed25519 key."""

    if commitments_url is None or did is None or not did_verified:
        return False

    async with _client_context(client=client, timeout_seconds=timeout_seconds) as active_client:
        payload = await _fetch_json_document(
            commitments_url,
            client=active_client,
            allow_private_network_targets=allow_private_network_targets,
        )
        if payload is None:
            return False

        normalized_payload = _normalize_required_commitments_fields(payload)
        if normalized_payload is None:
            return False

        if normalized_payload["agent_did"] != did:
            return False

        did_document = await _fetch_did_document(
            did,
            client=active_client,
            allow_private_network_targets=allow_private_network_targets,
        )
        if did_document is None:
            return False

        public_key = _extract_ed25519_public_key_bytes(did_document, did)
        if public_key is None:
            return False

        signature = _decode_signature(normalized_payload["signature"])
        if signature is None or len(signature) != 64:
            return False

        canonical_payload = _canonical_commitments_payload(normalized_payload)

        try:
            VerifyKey(public_key).verify(canonical_payload, signature)
        except BadSignatureError:
            return False

    return True
