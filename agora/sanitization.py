"""Helpers for sanitizing untrusted text before rendering in UI."""

from __future__ import annotations


def sanitize_ui_text(value: str | None, *, max_length: int = 5000) -> str:
    """Strip unsafe control characters and cap length for rendered text."""

    if value is None:
        return ""

    trimmed = value[:max_length]
    safe_chars = []
    for char in trimmed:
        codepoint = ord(char)
        if char in {"\n", "\r", "\t"} or codepoint >= 32:
            safe_chars.append(char)
    return "".join(safe_chars)


def sanitize_storage_text(value: str, *, max_length: int = 10000) -> str:
    """Sanitize text before persistence, removing control characters."""

    return sanitize_ui_text(value, max_length=max_length)


def sanitize_json_strings(value: object) -> object:
    """Recursively sanitize all strings inside JSON-like payloads."""

    if isinstance(value, str):
        return sanitize_storage_text(value)
    if isinstance(value, list):
        return [sanitize_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_json_strings(item) for key, item in value.items()}
    return value
