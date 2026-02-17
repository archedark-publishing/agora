"""Security helpers for API key hashing, verification, and migration."""

from __future__ import annotations

import hmac
import re
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_LEGACY_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_API_KEY_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
)


def hash_api_key(api_key: str) -> str:
    """Return an Argon2id hash for an API key."""

    return _API_KEY_HASHER.hash(api_key)


def _hash_api_key_legacy(api_key: str) -> str:
    return sha256(api_key.encode("utf-8")).hexdigest()


def api_key_fingerprint(api_key: str) -> str:
    """Return deterministic fingerprint for rate-limit bucketing/log correlation."""

    return _hash_api_key_legacy(api_key)


def is_legacy_api_key_hash(stored_hash: str | None) -> bool:
    """Return True when the stored hash uses legacy unsalted SHA-256."""

    if stored_hash is None:
        return False
    return bool(_LEGACY_SHA256_RE.fullmatch(stored_hash))


def verify_api_key(provided_api_key: str, stored_hash: str | None) -> bool:
    """
    Verify API key against a stored hash using constant-time comparison.

    A missing stored hash is treated as a failed verification.
    """

    if stored_hash is None:
        return False

    if is_legacy_api_key_hash(stored_hash):
        provided_hash = _hash_api_key_legacy(provided_api_key)
        return hmac.compare_digest(provided_hash, stored_hash)

    try:
        return _API_KEY_HASHER.verify(stored_hash, provided_api_key)
    except (InvalidHashError, VerifyMismatchError):
        return False


def should_rehash_api_key_hash(stored_hash: str | None) -> bool:
    """
    Return True when a stored hash should be upgraded.

    Legacy SHA-256 hashes are always upgradable, and Argon2 hashes are upgraded
    whenever hasher parameters evolve.
    """

    if stored_hash is None:
        return False
    if is_legacy_api_key_hash(stored_hash):
        return True
    try:
        return _API_KEY_HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
