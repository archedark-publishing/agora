"""add reputation tables and reliability materialized view

Revision ID: 20260223_0004
Revises: 20260217_0003
Create Date: 2026-02-23 13:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260223_0004"
down_revision = "20260217_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_reliability_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("reporter_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("interaction_date", sa.Date(), nullable=False),
        sa.Column("response_received", sa.Boolean(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("response_valid", sa.Boolean(), nullable=True),
        sa.Column("terms_honored", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_reliability_response_time_non_negative",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(notes) <= 2000",
            name="ck_reliability_notes_max_len",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reliability_subject_reported",
        "agent_reliability_reports",
        ["subject_agent_id", "reported_at"],
        unique=False,
    )
    op.create_index(
        "idx_reliability_reporter_subject",
        "agent_reliability_reports",
        ["reporter_agent_id", "subject_agent_id"],
        unique=False,
    )

    op.create_table(
        "agent_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("reporter_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("principal_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subject_response", sa.Text(), nullable=True),
        sa.Column("subject_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "visibility",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
        sa.CheckConstraint(
            "category IN ('refusal', 'boundary_test', 'error_handling', 'unexpected_behavior', 'resolution', 'disclosure')",
            name="ck_incident_category",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('resolved_well', 'resolved_poorly', 'unresolved', 'ongoing')",
            name="ck_incident_outcome",
        ),
        sa.CheckConstraint(
            "length(description) BETWEEN 50 AND 2000",
            name="ck_incident_description_len",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'principal_only', 'private')",
            name="ck_incident_visibility",
        ),
        sa.CheckConstraint(
            "subject_response IS NULL OR length(subject_response) BETWEEN 10 AND 2000",
            name="ck_incident_subject_response_len",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_incidents_subject_reported",
        "agent_incidents",
        ["subject_agent_id", "reported_at"],
        unique=False,
    )
    op.create_index(
        "idx_incidents_reporter_subject",
        "agent_incidents",
        ["reporter_agent_id", "subject_agent_id"],
        unique=False,
    )
    op.create_index("idx_incidents_category", "agent_incidents", ["category"], unique=False)
    op.create_index("idx_incidents_outcome", "agent_incidents", ["outcome"], unique=False)
    op.create_index("idx_incidents_visibility", "agent_incidents", ["visibility"], unique=False)

    op.execute(
        """
        CREATE MATERIALIZED VIEW agent_reliability_scores AS
        SELECT
            subject_agent_id,
            COUNT(*) AS total_reports,
            AVG(CASE WHEN response_received THEN 1.0 ELSE 0.0 END) AS response_rate,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time_ms)
                FILTER (WHERE response_time_ms IS NOT NULL) AS latency_p50,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms)
                FILTER (WHERE response_time_ms IS NOT NULL) AS latency_p95,
            AVG(CASE WHEN response_valid THEN 1.0 ELSE 0.0 END) AS validity_rate,
            AVG(CASE WHEN terms_honored THEN 1.0 ELSE 0.0 END) AS terms_honor_rate,
            MAX(reported_at) AS last_report_at
        FROM agent_reliability_reports
        WHERE reported_at > NOW() - INTERVAL '30 days'
        GROUP BY subject_agent_id
        """
    )
    op.create_index(
        "idx_reliability_scores_subject",
        "agent_reliability_scores",
        ["subject_agent_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_reliability_scores_subject", table_name="agent_reliability_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_reliability_scores")

    op.drop_index("idx_incidents_visibility", table_name="agent_incidents")
    op.drop_index("idx_incidents_outcome", table_name="agent_incidents")
    op.drop_index("idx_incidents_category", table_name="agent_incidents")
    op.drop_index("idx_incidents_reporter_subject", table_name="agent_incidents")
    op.drop_index("idx_incidents_subject_reported", table_name="agent_incidents")
    op.drop_table("agent_incidents")

    op.drop_index("idx_reliability_reporter_subject", table_name="agent_reliability_reports")
    op.drop_index("idx_reliability_subject_reported", table_name="agent_reliability_reports")
    op.drop_table("agent_reliability_reports")
