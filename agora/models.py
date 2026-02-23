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
    "refusal",
    "boundary_test",
    "error_handling",
    "unexpected_behavior",
    "resolution",
    "disclosure",
)
INCIDENT_OUTCOMES = (
    "resolved_well",
    "resolved_poorly",
    "unresolved",
    "ongoing",
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
        CheckConstraint(
            r"protocol_version ~ '^\d+\.\d+\.\d+$'",
            name="valid_protocol_version",
        ),
        Index("idx_agents_skills", "skills", postgresql_using="gin"),
        Index("idx_agents_capabilities", "capabilities", postgresql_using="gin"),
        Index("idx_agents_tags", "tags", postgresql_using="gin"),
        Index("idx_agents_health", "health_status"),
        Index("idx_agents_name", "name"),
        Index("idx_agents_last_healthy_at", "last_healthy_at"),
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
    protocol_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'0.3.0'"),
    )

    # Full card + extracted search fields
    agent_card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    skills: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    capabilities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    input_modes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    output_modes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

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


class AgentReliabilityReport(Base):
    """Caller-submitted reliability signal for a subject agent."""

    __tablename__ = "agent_reliability_reports"
    __table_args__ = (
        CheckConstraint("response_time_ms IS NULL OR response_time_ms >= 0", name="ck_reliability_response_time_non_negative"),
        CheckConstraint("notes IS NULL OR length(notes) <= 2000", name="ck_reliability_notes_max_len"),
        Index("idx_reliability_subject_reported", "subject_agent_id", "reported_at"),
        Index("idx_reliability_reporter_subject", "reporter_agent_id", "subject_agent_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    reporter_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    interaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    response_received: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    terms_honored: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class AgentIncident(Base):
    """Incident records that provide trust context beyond reliability metrics."""

    __tablename__ = "agent_incidents"
    __table_args__ = (
        CheckConstraint(
            "category IN ('refusal', 'boundary_test', 'error_handling', 'unexpected_behavior', 'resolution', 'disclosure')",
            name="ck_incident_category",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('resolved_well', 'resolved_poorly', 'unresolved', 'ongoing')",
            name="ck_incident_outcome",
        ),
        CheckConstraint("length(description) BETWEEN 50 AND 2000", name="ck_incident_description_len"),
        CheckConstraint(
            "visibility IN ('public', 'principal_only', 'private')",
            name="ck_incident_visibility",
        ),
        CheckConstraint(
            "subject_response IS NULL OR length(subject_response) BETWEEN 10 AND 2000",
            name="ck_incident_subject_response_len",
        ),
        Index("idx_incidents_subject_reported", "subject_agent_id", "reported_at"),
        Index("idx_incidents_reporter_subject", "reporter_agent_id", "subject_agent_id"),
        Index("idx_incidents_category", "category"),
        Index("idx_incidents_outcome", "outcome"),
        Index("idx_incidents_visibility", "visibility"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    reporter_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    principal_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    subject_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'public'"),
    )
