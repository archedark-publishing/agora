from agora.security import hash_api_key, verify_api_key


def test_hash_and_verify_api_key() -> None:
    digest = hash_api_key("test-key")
    assert len(digest) == 64
    assert verify_api_key("test-key", digest) is True
    assert verify_api_key("wrong-key", digest) is False
    assert verify_api_key("test-key", None) is False
