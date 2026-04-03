from __future__ import annotations

import agora.main as main_module


def test_merge_agent_card_payload_keeps_explicit_name_and_description() -> None:
    payload = {
        "agent_card_url": "https://example.com",
        "name": "Override Name",
        "description": "Override description",
    }
    fetched_card = {
        "name": "Fetched Name",
        "description": "Fetched description",
        "url": "https://example.com/agents/fetched",
        "version": "1.0.0",
    }

    merged = main_module._merge_agent_card_payload(payload, fetched_card)

    assert merged["name"] == "Override Name"
    assert merged["description"] == "Override description"
    assert merged["url"] == "https://example.com/agents/fetched"
    assert "url" not in payload


def test_merge_agent_card_payload_populates_missing_url() -> None:
    payload = {
        "agent_card_url": "https://example.com",
        "name": "Override Name",
    }
    fetched_card = {
        "url": "https://example.com/agents/fetched",
        "version": "1.0.0",
    }

    merged = main_module._merge_agent_card_payload(payload, fetched_card)

    assert merged["url"] == "https://example.com/agents/fetched"
