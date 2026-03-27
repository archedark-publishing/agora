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


async def verify_agent_json_manifest(
    *,
    agent_url: str,
    client: httpx.AsyncClient,
    allow_private_network_targets: bool,
) -> bool:
    """
    Verify agent.json v1.4 schema + domain binding (+ optional DID binding).

    Notes:
    - Missing or invalid `/.well-known/agent.json` is treated as not verified.
    - If `identity.did` is present but DID document is unreachable, verification remains true
      (soft signal) as long as schema + domain + DID string match pass.
    """

    manifest_url = build_agent_json_url(agent_url)
    manifest_payload = await _fetch_json_document(
        manifest_url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    if manifest_payload is None:
        return False

    try:
        manifest = AgentJsonManifest.model_validate(manifest_payload)
    except ValidationError:
        return False

    try:
        registered_origin = _normalized_origin(agent_url)
        manifest_origin = _normalized_origin(str(manifest.url))
    except ValueError:
        return False

    if manifest_origin != registered_origin:
        return False

    manifest_did = manifest.identity.did if manifest.identity else None
    if not manifest_did:
        return True

    try:
        expected_did = _expected_did_web_id(agent_url)
        did_document_url = f"https://{urlsplit(agent_url).hostname}{_DID_DOCUMENT_PATH}"
    except ValueError:
        return False

    if manifest_did != expected_did:
        return False

    did_document = await _fetch_json_document(
        did_document_url,
        client=client,
        allow_private_network_targets=allow_private_network_targets,
    )
    if did_document is None:
        # Soft signal: keep manifest verified if DID endpoint is not yet reachable.
        return True

    return did_document.get("id") == expected_did
