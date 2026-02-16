"""SQLAlchemy ORM models for Agora."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


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
    owner_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
