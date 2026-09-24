"""Unit tests for Agora v2 minimal directory helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

import agora.main as main_module
from agora.main import (
    _email_verification_url,
    _issue_email_verification_token,
    _normalize_capability_list,
    _normalize_email_field,
    _parse_email_verification_token,
    _slugify_name,
    _verification_email_text,
)


def test_slugify_name_basic() -> None:
    assert _slugify_name("Ada") == "ada"
    assert _slugify_name("Mama's Little Helper") == "mama-s-little-helper"
    assert _slugify_name("  Terminator 2  ") == "terminator-2"


def test_slugify_name_unicode_and_empty() -> None:
    assert _slugify_name("Café Bot ☕") == "cafe-bot"
    assert _slugify_name("!!!") == "agent"


def test_slugify_name_truncates() -> None:
    long_name = "a" * 200
    assert len(_slugify_name(long_name)) == 60


def test_normalize_email_field_ok() -> None:
    assert _normalize_email_field(field_name="email", value="Ada@Example.COM") == "Ada@example.com"
    assert (
        _normalize_email_field(field_name="email", value="  mlh@archefire.com ")
        == "mlh@archefire.com"
    )


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, "not-an-email", "missing@tld", "@nodomain.com", "a" * 321 + "@x.com"],
)
def test_normalize_email_field_rejects(value) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _normalize_email_field(field_name="email", value=value)
    assert exc_info.value.status_code == 400


def test_normalize_capability_list_ok() -> None:
    assert _normalize_capability_list(None) is None
    assert _normalize_capability_list([]) is None
    assert _normalize_capability_list(["  email ", "", "scheduling"]) == ["email", "scheduling"]


def test_normalize_capability_list_rejects() -> None:
    with pytest.raises(HTTPException):
        _normalize_capability_list("not-a-list")
    with pytest.raises(HTTPException):
        _normalize_capability_list(["x" * 121])
    with pytest.raises(HTTPException):
        _normalize_capability_list(["ok"] * 51)


def test_email_verification_token_round_trip() -> None:
    agent_id = uuid4()
    token = _issue_email_verification_token(agent_id, "ada@example.com")
    assert "." in token
    parsed = _parse_email_verification_token(token)
    assert parsed == (agent_id, "ada@example.com")


def test_email_verification_token_rejects_tampering() -> None:
    agent_id = uuid4()
    token = _issue_email_verification_token(agent_id, "ada@example.com")
    payload_b64, sig_b64 = token.split(".", 1)
    # Flip a character in the payload: signature must no longer match.
    tampered = ("A" if payload_b64[0] != "A" else "B") + payload_b64[1:]
    assert _parse_email_verification_token(f"{tampered}.{sig_b64}") is None
    assert _parse_email_verification_token("not-a-token") is None
    assert _parse_email_verification_token("") is None


def test_email_verification_token_rejects_expired(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "email_verification_ttl_hours", -1)
    token = _issue_email_verification_token(uuid4(), "ada@example.com")
    assert _parse_email_verification_token(token) is None


def test_email_verification_url_shape() -> None:
    url = _email_verification_url(uuid4(), "ada@example.com")
    assert url.startswith("https://the-agora.dev/verify-email?token=")


def test_verification_email_text_mentions_link_and_expiry() -> None:
    text = _verification_email_text(
        agent_name="Ada",
        email="ada@example.com",
        verify_url="https://the-agora.dev/verify-email?token=abc",
    )
    assert "ada@example.com" in text
    assert "https://the-agora.dev/verify-email?token=abc" in text
    assert "48 hours" in text
