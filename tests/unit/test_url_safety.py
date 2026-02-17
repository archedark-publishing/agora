import socket
import asyncio
import ipaddress

from agora.url_safety import (
    URLSafetyError,
    assert_url_safe_for_outbound,
    assert_url_safe_for_registration,
    pin_hostname_resolution,
)


def test_registration_rejects_unresolvable_hostname_by_default(monkeypatch) -> None:
    def _raise(_hostname: str) -> list[object]:
        raise socket.gaierror("boom")

    monkeypatch.setattr("agora.url_safety._resolve_ips", _raise)
    try:
        assert_url_safe_for_registration("https://unresolved.example.test/a2a")
    except URLSafetyError as exc:
        assert "resolve" in str(exc).lower()
        return
    assert False, "Expected URLSafetyError for unresolved hostname"


def test_registration_can_allow_unresolvable_when_explicit(monkeypatch) -> None:
    def _raise(_hostname: str) -> list[object]:
        raise socket.gaierror("boom")

    monkeypatch.setattr("agora.url_safety._resolve_ips", _raise)
    assert_url_safe_for_registration(
        "https://unresolved.example.test/a2a",
        allow_unresolvable=True,
    )


def test_outbound_resolution_returns_pinned_target(monkeypatch) -> None:
    monkeypatch.setattr(
        "agora.url_safety._resolve_ips",
        lambda _hostname: [ipaddress.ip_address("93.184.216.34")],
    )
    target = assert_url_safe_for_outbound("https://example.test/.well-known/agora-verify")
    assert target.hostname == "example.test"
    assert str(target.pinned_ip) == "93.184.216.34"


def test_pin_hostname_resolution_overrides_runtime_dns(monkeypatch) -> None:
    original = socket.getaddrinfo

    def _dynamic(host: object, port: object, *args: object, **kwargs: object):
        host_text = host.decode("ascii", errors="ignore") if isinstance(host, bytes) else str(host)
        if host_text == "rebind.example.test":
            return original("127.0.0.1", port, *args, **kwargs)
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _dynamic)

    async def _run() -> None:
        async with pin_hostname_resolution("rebind.example.test", "93.184.216.34"):
            pinned_records = socket.getaddrinfo("rebind.example.test", 443, type=socket.SOCK_STREAM)
            assert pinned_records[0][4][0] == "93.184.216.34"

        rebound_records = socket.getaddrinfo("rebind.example.test", 443, type=socket.SOCK_STREAM)
        assert rebound_records[0][4][0] == "127.0.0.1"

    asyncio.run(_run())
