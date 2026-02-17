from hashlib import sha256

from agora.security import (
    hash_api_key,
    is_legacy_api_key_hash,
    should_rehash_api_key_hash,
    verify_api_key,
)


def test_hash_and_verify_api_key_argon2() -> None:
    digest = hash_api_key("test-key")
    assert digest.startswith("$argon2id$")
    assert verify_api_key("test-key", digest) is True
    assert verify_api_key("wrong-key", digest) is False
    assert should_rehash_api_key_hash(digest) is False
    assert verify_api_key("test-key", None) is False


def test_legacy_sha256_hashes_still_verify_and_upgrade() -> None:
    legacy_digest = sha256("legacy-key".encode("utf-8")).hexdigest()
    assert is_legacy_api_key_hash(legacy_digest) is True
    assert verify_api_key("legacy-key", legacy_digest) is True
    assert verify_api_key("wrong-key", legacy_digest) is False
    assert should_rehash_api_key_hash(legacy_digest) is True
