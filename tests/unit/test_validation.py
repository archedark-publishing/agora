from agora.validation import AgentCardValidationError, validate_agent_card


def _valid_payload() -> dict:
    return {
        "protocolVersion": "0.3.0",
        "name": "Validation Agent",
        "description": "Does validation tests",
        "url": "https://validation.example.com/a2a",
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [
            {
                "id": "validate",
                "name": "Validate",
                "description": "Validation",
                "tags": ["qa", "test"],
                "inputModes": ["text/plain"],
                "outputModes": ["application/json"],
            }
        ],
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
    }


def test_validate_agent_card_extracts_fields() -> None:
    validated = validate_agent_card(_valid_payload())
    assert validated.skills == ["validate"]
    assert validated.capabilities == ["streaming"]
    assert validated.tags == ["qa", "test"]
    assert validated.input_modes == ["application/json", "text/plain"]


def test_validate_agent_card_requires_skills() -> None:
    payload = _valid_payload()
    payload["skills"] = []

    try:
        validate_agent_card(payload)
    except AgentCardValidationError as exc:
        assert any(error["field"] == "skills" for error in exc.errors)
        return
    assert False, "Expected AgentCardValidationError when skills are missing"


def test_validate_agent_card_rejects_oversized_name() -> None:
    payload = _valid_payload()
    payload["name"] = "n" * 5000

    try:
        validate_agent_card(payload)
    except AgentCardValidationError as exc:
        assert any(error["field"] == "name" for error in exc.errors)
        return
    assert False, "Expected AgentCardValidationError for oversized name"
