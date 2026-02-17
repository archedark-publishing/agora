"""Safety checks for URL targets to reduce SSRF risk."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class URLSafetyError(ValueError):
    """Raised when a URL target is unsafe for storage/outbound use."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    resolved: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for record in records:
        raw_ip = record[4][0]
        resolved.append(ipaddress.ip_address(raw_ip))
    return resolved


def _validate_hostname(hostname: str | None, *, allow_private: bool) -> None:
    if not hostname:
        raise URLSafetyError("URL must include a hostname")

    lowered = hostname.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        raise URLSafetyError("Private or internal network targets are not allowed")

    try:
        literal_ip = ipaddress.ip_address(lowered)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if not allow_private and _is_blocked_ip(literal_ip):
            raise URLSafetyError("Private or internal network targets are not allowed")
        return

    if allow_private:
        return

    try:
        resolved_ips = _resolve_ips(hostname)
    except socket.gaierror:
        # Keep behavior permissive for unresolved public hostnames at registration time.
        return

    if any(_is_blocked_ip(ip) for ip in resolved_ips):
        raise URLSafetyError("Private or internal network targets are not allowed")


def assert_url_safe_for_registration(url: str, *, allow_private: bool = False) -> None:
    """Validate that a user-submitted URL does not target internal/private networks."""

    parts = urlsplit(url)
    _validate_hostname(parts.hostname, allow_private=allow_private)


def assert_url_safe_for_outbound(url: str, *, allow_private: bool = False) -> None:
    """Validate that an outbound request URL resolves to safe public targets."""

    parts = urlsplit(url)
    _validate_hostname(parts.hostname, allow_private=allow_private)

    if allow_private:
        return

    hostname = parts.hostname
    if hostname is None:
        raise URLSafetyError("URL must include a hostname")

    try:
        resolved_ips = _resolve_ips(hostname)
    except socket.gaierror as exc:
        raise URLSafetyError("Unable to resolve target hostname") from exc

    if any(_is_blocked_ip(ip) for ip in resolved_ips):
        raise URLSafetyError("Private or internal network targets are not allowed")
