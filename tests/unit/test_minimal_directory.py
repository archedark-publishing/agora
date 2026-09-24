"""Unit tests for Agora v2 minimal directory helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from agora.main import (
    _normalize_capability_list,
    _normalize_email_field,
    _slugify_name,
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
