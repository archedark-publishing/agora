"""agent.json v1.4 verification helpers."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator

from agora.url_safety import URLSafetyError, assert_url_safe_for_outbound, pin_hostname_resolution

_AGENT_JSON_PATH = "/.well-known/agent.json"
_DID_DOCUMENT_PATH = "/.well-known/did.json"


class AgentJsonIdentity(BaseModel):
    """Optional identity metadata in agent.json v1.4."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    did: str | None = None
    oatr_issuer_id: str | None = Field(default=None, max_length=255)


class AgentJsonManifest(BaseModel):
    """Subset of agent.json v1.4 fields needed for Agora verification."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    url: Annotated[AnyHttpUrl, Field(max_length=2048)]
    protocol_version: str = Field(alias="protocolVersion", min_length=1, max_length=64)
    skills: list[Any] = Field(min_length=1)
    identity: AgentJsonIdentity | None = None

    @field_validator("url")
    @classmethod
    def _validate_url_length(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > 2048:
            raise ValueError("String should have at most 2048 characters")
        return value


def _normalized_origin(url: str) -> str:
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must include hostname")

    port = parts.port
    include_port = bool(port) and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    )
    if include_port:
        return f"{scheme}://{hostname}:{port}"
    return f"{scheme}://{hostname}"


def build_agent_json_url(agent_url: str) -> str:
    """Resolve the canonical agent.json endpoint for an agent URL."""

    return f"{_normalized_origin(agent_url)}{_AGENT_JSON_PATH}"


def _expected_did_web_id(agent_url: str) -> str:
    host = (urlsplit(agent_url).hostname or "").lower()
    if not host:
        raise ValueError("Agent URL must include hostname")
    return f"did:web:{host}"


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


def _inline_commitments_count(commitments_payload: Any) -> int | None:
    if isinstance(commitments_payload, list):
        return len(commitments_payload)

    if not isinstance(commitments_payload, dict):
        return None

    for numeric_key in ("count", "commitment_count", "total"):
        raw_value = commitments_payload.get(numeric_key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int) and raw_value >= 0:
            return raw_value

    for list_key in ("commitments", "items"):
        raw_items = commitments_payload.get(list_key)
        if isinstance(raw_items, list):
            return len(raw_items)

    return None


def _inline_commitments_summary(commitments_payload: Any) -> str | None:
    if not isinstance(commitments_payload, dict):
        return None

    raw_summary = commitments_payload.get("summary")
    if not isinstance(raw_summary, str):
        return None

    normalized = raw_summary.strip()
    if not normalized:
        return None

    return normalized[:2000]


def _extract_inline_commitments_metadata(
    *,
    manifest_payload: dict[str, Any],
    protocol_version: str,
) -> tuple[int | None, str | None]:
    if not protocol_version.startswith("1.4"):
        return None, None

    inline_commitments = manifest_payload.get("commitments")
    if inline_commitments is None:
        return None, None

    return (
        _inline_commitments_count(inline_commitments),
        _inline_commitments_summary(inline_commitments),
    )


async def verify_agent_json_manifest_with_indexing_metadata(
    *,
    agent_url: str,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> tuple[bool, str | None, int | None, str | None]:
    """
    Verify agent.json v1.4 schema + domain binding (+ optional DID binding).

    Returns:
        tuple[bool, str | None, int | None, str | None]:
            - verified flag
            - identity.oatr_issuer_id extracted from the manifest
            - inline commitments count (if provided)
            - inline commitments summary (if provided)
    """

    manifest_url = build_agent_json_url(agent_url)
    manifest_payload = await _fetch_json_document(
        manifest_url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    if manifest_payload is None:
        return False, None, None, None

    try:
        manifest = AgentJsonManifest.model_validate(manifest_payload)
    except ValidationError:
        return False, None, None, None

    try:
        registered_origin = _normalized_origin(agent_url)
        manifest_origin = _normalized_origin(str(manifest.url))
    except ValueError:
        return False, None, None, None

    if manifest_origin != registered_origin:
        return False, None, None, None

    oatr_issuer_id = manifest.identity.oatr_issuer_id if manifest.identity else None
    commitments_count, commitments_summary = _extract_inline_commitments_metadata(
        manifest_payload=manifest_payload,
        protocol_version=manifest.protocol_version,
    )

    manifest_did = manifest.identity.did if manifest.identity else None
    if not manifest_did:
        return True, oatr_issuer_id, commitments_count, commitments_summary

    try:
        expected_did = _expected_did_web_id(agent_url)
        did_document_url = f"https://{urlsplit(agent_url).hostname}{_DID_DOCUMENT_PATH}"
    except ValueError:
        return False, None, None, None

    if manifest_did != expected_did:
        return False, None, None, None

    did_document = await _fetch_json_document(
        did_document_url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    if did_document is None:
        # Soft signal: keep manifest verified if DID endpoint is not yet reachable.
        return True, oatr_issuer_id, commitments_count, commitments_summary

    if did_document.get("id") != expected_did:
        return False, None, None, None

    return True, oatr_issuer_id, commitments_count, commitments_summary


async def verify_agent_json_manifest(
    *,
    agent_url: str,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> bool:
    """Backward-compatible bool-only wrapper for agent.json verification."""

    verified, _oatr_issuer_id, _commitments_count, _commitments_summary = (
        await verify_agent_json_manifest_with_indexing_metadata(
            agent_url=agent_url,
            client=client,
            allow_private_network_targets=allow_private_network_targets,
        )
    )
    return verified
