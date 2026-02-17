"""Strict URL canonicalization helpers for agent identity URLs."""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit, urlunsplit


class URLNormalizationError(ValueError):
    """Raised when an agent URL cannot be normalized."""


def _build_normalized_netloc(parts: SplitResult, scheme: str) -> str:
    hostname = parts.hostname
    if not hostname:
        raise URLNormalizationError("URL must include a host")

    if "@" in parts.netloc:
        raise URLNormalizationError("URL userinfo is not allowed")

    host = hostname
    if ":" in host and not host.startswith("["):
        # Re-wrap IPv6 literals in brackets for proper URL formatting.
        host = f"[{host}]"

    try:
        port = parts.port
    except ValueError as exc:
        raise URLNormalizationError("URL has an invalid port") from exc

    default_port = 80 if scheme == "http" else 443
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{host}{port_suffix}"


def normalize_url(url: str) -> str:
    """Normalize URLs using the strict MVP canonicalization rules."""

    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise URLNormalizationError("URL is invalid") from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise URLNormalizationError("URL scheme must be http or https")

    netloc = _build_normalized_netloc(parts, scheme)
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    # Preserve query exactly as provided and always drop fragments.
    return urlunsplit((scheme, netloc, path, parts.query, ""))
