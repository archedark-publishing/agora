"""SQLAlchemy ORM models for Agora."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


RELIABILITY_WINDOW_DAYS = 30
INCIDENT_CATEGORIES = (
    "refusal_to_comply",
    "deceptive_output",
    "data_handling_concern",
    "capability_misrepresentation",
    "positive_exceptional_service",
    "other",
)
INCIDENT_OUTCOMES = (
    "resolved_well",
    "resolved_poorly",
    "ongoing",
    "unresolved",
)
INCIDENT_VISIBILITIES = (
    "public",
    "principal_only",
    "private",
)


class Agent(Base):
    """Agent registry record."""

    __tablename__ = "agents"
    __table_args__ = (
        Index("idx_agents_skills", "skills", postgresql_using="gin"),
        Index("idx_agents_capabilities", "capabilities", postgresql_using="gin"),
        Index("idx_agents_tags", "tags", postgresql_using="gin"),
        Index("idx_agents_health", "health_status"),
        Index("idx_agents_name", "name"),
        Index("idx_agents_last_healthy_at", "last_healthy_at"),
        Index("idx_agents_econ_id", "econ_id"),
        Index("idx_agents_did", "did"),
        Index("idx_agents_did_verified", "did_verified"),
        Index("idx_agents_protocol_version", "protocol_version"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # Core A2A Agent Card fields
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Full card + extracted search fields
    agent_card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    capabilities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    input_modes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    output_modes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    agent_card_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    econ_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    did: Mapped[str | None] = mapped_column(String(512), nullable=True)
    did_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    erc8004_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    operator: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Ownership + metadata
    owner_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    health_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'unknown'"),
    )

    # Interview decision additions
    last_healthy_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recovery_challenge_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    recovery_session_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    recovery_challenge_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recovery_challenge_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    operator_challenge_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    operator_challenge_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    operator_challenge_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AgentReliabilityReport(Base):
    """Caller-submitted reliability signal for a subject agent."""

    __tablename__ = "reliability_reports"
    __table_args__ = (
        CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_reliability_response_time_non_negative",
        ),
        CheckConstraint(
            "notes IS NULL OR length(notes) <= 2000",
            name="ck_reliability_notes_max_len",
        ),
        Index("idx_reliability_agent_created", "agent_id", "created_at"),
        Index("idx_reliability_reporter_agent", "reporter_agent_id", "agent_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    interaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    response_received: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    terms_honored: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AgentIncident(Base):
    """Incident records that provide trust context beyond reliability metrics."""

    __tablename__ = "incident_reports"
    __table_args__ = (
        CheckConstraint(
            (
                "category IN ('refusal_to_comply', 'deceptive_output', 'data_handling_concern', "
                "'capability_misrepresentation', 'positive_exceptional_service', 'other')"
            ),
            name="ck_incident_category",
        ),
        CheckConstraint(
            "outcome IN ('resolved_well', 'resolved_poorly', 'ongoing', 'unresolved')",
            name="ck_incident_outcome",
        ),
        CheckConstraint(
            "visibility IN ('public', 'principal_only', 'private')",
            name="ck_incident_visibility",
        ),
        Index("idx_incidents_agent_created", "agent_id", "created_at"),
        Index("idx_incidents_reporter_agent", "reporter_agent_id", "agent_id"),
        Index("idx_incidents_category", "category"),
        Index("idx_incidents_outcome", "outcome"),
        Index("idx_incidents_visibility", "visibility"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'public'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
