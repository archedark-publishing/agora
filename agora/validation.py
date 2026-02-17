"""A2A Agent Card validation and field extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_AGENT_NAME_LENGTH = 255
MAX_AGENT_DESCRIPTION_LENGTH = 4000
MAX_AGENT_URL_LENGTH = 2048
MAX_AGENT_VERSION_LENGTH = 50
MAX_PROTOCOL_VERSION_LENGTH = 20
MAX_SKILL_ID_LENGTH = 255
MAX_SKILL_NAME_LENGTH = 255
MAX_SKILL_DESCRIPTION_LENGTH = 2000


class SkillCard(BaseModel):
    """Subset of the A2A skill schema used by Agora MVP."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=MAX_SKILL_ID_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_SKILL_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    tags: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(default_factory=list, alias="inputModes")
    output_modes: list[str] = Field(default_factory=list, alias="outputModes")
    examples: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """Subset of A2A Agent Card schema required for MVP."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    protocol_version: str = Field(
        alias="protocolVersion",
        pattern=r"^\d+\.\d+\.\d+$",
        max_length=MAX_PROTOCOL_VERSION_LENGTH,
    )
    name: str = Field(min_length=1, max_length=MAX_AGENT_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_AGENT_DESCRIPTION_LENGTH)
    url: Annotated[AnyHttpUrl, Field(max_length=MAX_AGENT_URL_LENGTH)]
    version: str | None = Field(default=None, max_length=MAX_AGENT_VERSION_LENGTH)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    skills: list[SkillCard] = Field(min_length=1)
    default_input_modes: list[str] = Field(default_factory=list, alias="defaultInputModes")
    default_output_modes: list[str] = Field(default_factory=list, alias="defaultOutputModes")
    authentication: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def _validate_url_length(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > MAX_AGENT_URL_LENGTH:
            raise ValueError(f"String should have at most {MAX_AGENT_URL_LENGTH} characters")
        return value


@dataclass(slots=True)
class ValidatedAgentCard:
    """Validated card plus extracted search-friendly fields."""

    card: AgentCard
    skills: list[str]
    tags: list[str]
    capabilities: list[str]
    input_modes: list[str]
    output_modes: list[str]


class AgentCardValidationError(ValueError):
    """Structured validation error container for API responses."""

    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("Agent Card validation failed")
        self.errors = errors

    @classmethod
    def from_pydantic_error(cls, exc: ValidationError) -> AgentCardValidationError:
        details: list[dict[str, str]] = []
        for err in exc.errors():
            field = ".".join(str(item) for item in err["loc"]) or "agent_card"
            details.append(
                {
                    "field": field,
                    "message": err["msg"],
                    "type": err["type"],
                }
            )
        return cls(details)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def validate_agent_card(agent_card_payload: dict[str, Any]) -> ValidatedAgentCard:
    """
    Validate an Agent Card payload and extract searchable fields.

    Raises:
        AgentCardValidationError: when the payload does not satisfy schema rules.
    """

    try:
        card = AgentCard.model_validate(agent_card_payload)
    except ValidationError as exc:
        raise AgentCardValidationError.from_pydantic_error(exc) from exc

    extracted_skills = _dedupe_preserving_order([skill.id for skill in card.skills])
    extracted_tags = _dedupe_preserving_order(
        [tag for skill in card.skills for tag in skill.tags if tag]
    )
    extracted_capabilities = _dedupe_preserving_order(
        [name for name, enabled in card.capabilities.items() if enabled]
    )
    extracted_input_modes = _dedupe_preserving_order(
        [*card.default_input_modes, *[mode for skill in card.skills for mode in skill.input_modes]]
    )
    extracted_output_modes = _dedupe_preserving_order(
        [*card.default_output_modes, *[mode for skill in card.skills for mode in skill.output_modes]]
    )

    return ValidatedAgentCard(
        card=card,
        skills=extracted_skills,
        tags=extracted_tags,
        capabilities=extracted_capabilities,
        input_modes=extracted_input_modes,
        output_modes=extracted_output_modes,
    )
