import socket

from agora.url_safety import URLSafetyError, assert_url_safe_for_registration


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
