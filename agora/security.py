"""Security helpers for API key hashing and verification."""

from __future__ import annotations

import hmac
from hashlib import sha256


def hash_api_key(api_key: str) -> str:
    """Return SHA-256 hex digest for an API key."""

    return sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(provided_api_key: str, stored_hash: str | None) -> bool:
    """
    Verify API key against a stored hash using constant-time comparison.

    A missing stored hash is treated as a failed verification.
    """

    if stored_hash is None:
        return False

    provided_hash = hash_api_key(provided_api_key)
    return hmac.compare_digest(provided_hash, stored_hash)
