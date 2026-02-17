"""Safety checks for URL targets to reduce SSRF risk."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import ipaddress
import socket
from threading import Lock
from urllib.parse import urlsplit


class URLSafetyError(ValueError):
    """Raised when a URL target is unsafe for storage/outbound use."""


@dataclass(frozen=True, slots=True)
class SafeOutboundTarget:
    """Pinned outbound target metadata used to prevent DNS rebinding."""

    hostname: str
    pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address


_dns_pin_lock = Lock()


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
    seen: set[str] = set()
    for record in records:
        raw_ip = record[4][0]
        if raw_ip in seen:
            continue
        seen.add(raw_ip)
        resolved.append(ipaddress.ip_address(raw_ip))
    return resolved


def _validate_hostname(
    hostname: str | None,
    *,
    allow_private: bool,
    allow_unresolvable: bool = False,
) -> None:
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
    except socket.gaierror as exc:
        if allow_unresolvable:
            return
        raise URLSafetyError("Unable to resolve target hostname") from exc

    if any(_is_blocked_ip(ip) for ip in resolved_ips):
        raise URLSafetyError("Private or internal network targets are not allowed")


def assert_url_safe_for_registration(
    url: str,
    *,
    allow_private: bool = False,
    allow_unresolvable: bool = False,
) -> None:
    """Validate that a user-submitted URL does not target internal/private networks."""

    parts = urlsplit(url)
    _validate_hostname(
        parts.hostname,
        allow_private=allow_private,
        allow_unresolvable=allow_unresolvable,
    )


def assert_url_safe_for_outbound(url: str, *, allow_private: bool = False) -> SafeOutboundTarget:
    """Validate an outbound URL and return a hostname/IP tuple for pinned fetches."""

    parts = urlsplit(url)
    hostname = parts.hostname
    if hostname is None:
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
        return SafeOutboundTarget(hostname=hostname, pinned_ip=literal_ip)

    try:
        resolved_ips = _resolve_ips(hostname)
    except socket.gaierror as exc:
        raise URLSafetyError("Unable to resolve target hostname") from exc

    if not resolved_ips:
        raise URLSafetyError("Unable to resolve target hostname")

    if not allow_private and any(_is_blocked_ip(ip) for ip in resolved_ips):
        raise URLSafetyError("Private or internal network targets are not allowed")

    return SafeOutboundTarget(hostname=hostname, pinned_ip=resolved_ips[0])


@asynccontextmanager
async def pin_hostname_resolution(
    hostname: str,
    pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str,
):
    """
    Temporarily pin DNS resolution for one hostname to one validated IP address.

    This closes the DNS check/use gap by ensuring outbound HTTP connection setup
    cannot re-resolve the hostname to a different address mid-request.
    """

    normalized_hostname = hostname.lower().rstrip(".")
    original_getaddrinfo = socket.getaddrinfo
    pinned_ip_str = str(pinned_ip)

    def _patched_getaddrinfo(host: object, port: object, *args: object, **kwargs: object):
        host_text: str
        if isinstance(host, bytes):
            host_text = host.decode("ascii", errors="ignore")
        else:
            host_text = str(host)
        if host_text.lower().rstrip(".") == normalized_hostname:
            return original_getaddrinfo(pinned_ip_str, port, *args, **kwargs)
        return original_getaddrinfo(host, port, *args, **kwargs)

    await asyncio.to_thread(_dns_pin_lock.acquire)
    socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
        _dns_pin_lock.release()
