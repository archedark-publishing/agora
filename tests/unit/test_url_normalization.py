from agora.url_normalization import URLNormalizationError, normalize_url


def test_normalize_url_applies_canonical_rules() -> None:
    assert normalize_url("https://Agent.Example.com:443/a2a/") == "https://agent.example.com/a2a"
    assert normalize_url("http://Example.com:80/") == "http://example.com/"
    assert normalize_url("https://agent.example.com/a2a?x=1#fragment") == "https://agent.example.com/a2a?x=1"


def test_normalize_url_rejects_invalid_scheme() -> None:
    try:
        normalize_url("ftp://example.com/a2a")
    except URLNormalizationError as exc:
        assert "scheme" in str(exc)
        return
    assert False, "Expected URLNormalizationError for unsupported scheme"


def test_normalize_url_rejects_userinfo() -> None:
    try:
        normalize_url("https://trusted.example.com@attacker.example.net/a2a")
    except URLNormalizationError as exc:
        assert "userinfo" in str(exc)
        return
    assert False, "Expected URLNormalizationError for URLs with userinfo"
