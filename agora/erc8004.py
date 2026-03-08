"""ERC-8004 registration discovery and econ_id verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from agora.url_safety import URLSafetyError, assert_url_safe_for_outbound, pin_hostname_resolution

ERC8004_REGISTRATION_TYPE = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
ERC8004_REGISTRATION_PATH = "/.well-known/agent-registration.json"


@dataclass(slots=True)
class ERC8004VerificationResult:
    """Computed econ_id + verification status after an ERC-8004 lookup."""

    econ_id: str | None
    verified: bool


def build_registration_url(endpoint_url: str) -> str:
    """Build canonical ERC-8004 registration file URL from an agent endpoint URL."""

    parts = urlsplit(endpoint_url)
    host = parts.hostname or ""
    port_fragment = f":{parts.port}" if parts.port else ""
    return f"https://{host}{port_fragment}{ERC8004_REGISTRATION_PATH}"


def _normalize_agent_registry(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_agent_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _extract_erc8004_registrations(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("Registration payload must be a JSON object")
    if payload.get("type") != ERC8004_REGISTRATION_TYPE:
        raise ValueError("Unsupported registration payload type")

    registrations = payload.get("registrations")
    if not isinstance(registrations, list):
        raise ValueError("registrations must be an array")

    econ_ids: list[str] = []
    for entry in registrations:
        if not isinstance(entry, dict):
            continue
        registry = _normalize_agent_registry(entry.get("agentRegistry"))
        agent_id = _normalize_agent_id(entry.get("agentId"))
        if registry and agent_id:
            econ_ids.append(f"{registry}:{agent_id}")

    if not econ_ids:
        raise ValueError("No valid registrations found")
    return econ_ids


async def discover_erc8004_registration_econ_id(
    endpoint_url: str,
    *,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> str | None:
    """Fetch and parse ERC-8004 registration metadata, returning the first econ_id candidate."""

    registration_url = build_registration_url(endpoint_url)

    try:
        safe_target = assert_url_safe_for_outbound(
            registration_url,
            allow_private=allow_private_network_targets,
        )
        async with pin_hostname_resolution(safe_target.hostname, safe_target.pinned_ip):
            response = await client.get(registration_url, follow_redirects=False)
    except (URLSafetyError, httpx.HTTPError):
        return None

    if response.status_code != httpx.codes.OK:
        return None

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    try:
        econ_ids = _extract_erc8004_registrations(payload)
    except ValueError:
        return None

    return econ_ids[0]


def resolve_erc8004_verification(
    existing_econ_id: str | None,
    discovered_econ_id: str | None,
) -> ERC8004VerificationResult:
    """Apply ERC-8004 match rules to existing/discovered econ_id values."""

    normalized_existing = existing_econ_id.strip() if isinstance(existing_econ_id, str) else None
    normalized_existing = normalized_existing or None

    if discovered_econ_id is None:
        return ERC8004VerificationResult(econ_id=normalized_existing, verified=False)

    if normalized_existing is None:
        return ERC8004VerificationResult(econ_id=discovered_econ_id, verified=True)

    return ERC8004VerificationResult(
        econ_id=normalized_existing,
        verified=normalized_existing == discovered_econ_id,
    )
