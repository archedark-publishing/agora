"""align reputation schema with phase 1 issue requirements

Revision ID: 20260307_0007
Revises: 20260303_0006
Create Date: 2026-03-07 19:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260307_0007"
down_revision = "20260303_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("agent_reliability_reports", "reliability_reports")
    op.rename_table("agent_incidents", "incident_reports")

    op.alter_column("reliability_reports", "subject_agent_id", new_column_name="agent_id")
    op.alter_column("reliability_reports", "reported_at", new_column_name="created_at")

    op.alter_column("incident_reports", "subject_agent_id", new_column_name="agent_id")
    op.alter_column("incident_reports", "reported_at", new_column_name="created_at")

    op.drop_index("idx_reliability_subject_reported", table_name="reliability_reports")
    op.drop_index("idx_reliability_reporter_subject", table_name="reliability_reports")
    op.create_index(
        "idx_reliability_agent_created",
        "reliability_reports",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_reliability_reporter_agent",
        "reliability_reports",
        ["reporter_agent_id", "agent_id"],
        unique=False,
    )

    op.drop_index("idx_incidents_subject_reported", table_name="incident_reports")
    op.drop_index("idx_incidents_reporter_subject", table_name="incident_reports")
    op.create_index(
        "idx_incidents_agent_created",
        "incident_reports",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_incidents_reporter_agent",
        "incident_reports",
        ["reporter_agent_id", "agent_id"],
        unique=False,
    )

    op.execute("UPDATE reliability_reports SET response_received = false WHERE response_received IS NULL")
    op.alter_column(
        "reliability_reports",
        "response_received",
        existing_type=sa.Boolean(),
        nullable=False,
    )

    op.drop_column("reliability_reports", "disputed")

    op.execute("UPDATE incident_reports SET outcome = 'unresolved' WHERE outcome IS NULL")
    op.execute(
        """
        UPDATE incident_reports
        SET category = CASE category
            WHEN 'refusal' THEN 'refusal_to_comply'
            WHEN 'boundary_test' THEN 'capability_misrepresentation'
            WHEN 'error_handling' THEN 'other'
            WHEN 'unexpected_behavior' THEN 'deceptive_output'
            WHEN 'resolution' THEN 'positive_exceptional_service'
            WHEN 'disclosure' THEN 'data_handling_concern'
            ELSE 'other'
        END
        """
    )

    op.drop_constraint("ck_incident_category", "incident_reports", type_="check")
    op.drop_constraint("ck_incident_outcome", "incident_reports", type_="check")
    op.drop_constraint("ck_incident_description_len", "incident_reports", type_="check")
    op.drop_constraint("ck_incident_subject_response_len", "incident_reports", type_="check")

    op.alter_column(
        "incident_reports",
        "outcome",
        existing_type=sa.String(length=32),
        nullable=False,
    )

    op.drop_column("incident_reports", "principal_verified")
    op.drop_column("incident_reports", "subject_responded_at")

    op.create_check_constraint(
        "ck_incident_category",
        "incident_reports",
        (
            "category IN ('refusal_to_comply', 'deceptive_output', 'data_handling_concern', "
            "'capability_misrepresentation', 'positive_exceptional_service', 'other')"
        ),
    )
    op.create_check_constraint(
        "ck_incident_outcome",
        "incident_reports",
        "outcome IN ('resolved_well', 'resolved_poorly', 'ongoing', 'unresolved')",
    )

    op.drop_index("idx_reliability_scores_subject", table_name="agent_reliability_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_reliability_scores")
    op.execute(
        """
        CREATE MATERIALIZED VIEW agent_reliability_scores AS
        SELECT
            agent_id,
            COUNT(*)::int AS sample_size,
            AVG(CASE WHEN response_received THEN 100.0 ELSE 0.0 END) AS uptime_pct,
            AVG(CASE WHEN response_valid THEN 100.0 ELSE 0.0 END) AS response_valid_pct,
            AVG(CASE WHEN terms_honored THEN 100.0 ELSE 0.0 END) AS terms_honored_pct,
            AVG(response_time_ms)::float AS avg_latency_ms,
            (
                COALESCE(AVG(CASE WHEN response_received THEN 100.0 ELSE 0.0 END), 0)
                + COALESCE(AVG(CASE WHEN response_valid THEN 100.0 ELSE 0.0 END), 0)
                + COALESCE(AVG(CASE WHEN terms_honored THEN 100.0 ELSE 0.0 END), 0)
            ) / 3.0 AS availability_score,
            MAX(created_at) AS last_report_at
        FROM reliability_reports
        WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY agent_id
        """
    )
    op.create_index(
        "idx_reliability_scores_agent",
        "agent_reliability_scores",
        ["agent_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_reliability_scores_agent", table_name="agent_reliability_scores")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_reliability_scores")
    op.execute(
        """
        CREATE MATERIALIZED VIEW agent_reliability_scores AS
        SELECT
            agent_id AS subject_agent_id,
            COUNT(*) AS total_reports,
            AVG(CASE WHEN response_received THEN 1.0 ELSE 0.0 END) AS response_rate,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time_ms)
                FILTER (WHERE response_time_ms IS NOT NULL) AS latency_p50,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms)
                FILTER (WHERE response_time_ms IS NOT NULL) AS latency_p95,
            AVG(CASE WHEN response_valid THEN 1.0 ELSE 0.0 END) AS validity_rate,
            AVG(CASE WHEN terms_honored THEN 1.0 ELSE 0.0 END) AS terms_honor_rate,
            MAX(created_at) AS last_report_at
        FROM reliability_reports
        WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY agent_id
        """
    )
    op.create_index(
        "idx_reliability_scores_subject",
        "agent_reliability_scores",
        ["subject_agent_id"],
        unique=True,
    )

    op.drop_constraint("ck_incident_outcome", "incident_reports", type_="check")
    op.drop_constraint("ck_incident_category", "incident_reports", type_="check")

    op.add_column(
        "incident_reports",
        sa.Column("principal_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "incident_reports",
        sa.Column("subject_responded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column(
        "incident_reports",
        "outcome",
        existing_type=sa.String(length=32),
        nullable=True,
    )

    op.create_check_constraint(
        "ck_incident_category",
        "incident_reports",
        "category IN ('refusal', 'boundary_test', 'error_handling', 'unexpected_behavior', 'resolution', 'disclosure')",
    )
    op.create_check_constraint(
        "ck_incident_outcome",
        "incident_reports",
        "outcome IS NULL OR outcome IN ('resolved_well', 'resolved_poorly', 'unresolved', 'ongoing')",
    )
    op.create_check_constraint(
        "ck_incident_description_len",
        "incident_reports",
        "length(description) BETWEEN 50 AND 2000",
    )
    op.create_check_constraint(
        "ck_incident_subject_response_len",
        "incident_reports",
        "subject_response IS NULL OR length(subject_response) BETWEEN 10 AND 2000",
    )

    op.drop_index("idx_incidents_reporter_agent", table_name="incident_reports")
    op.drop_index("idx_incidents_agent_created", table_name="incident_reports")
    op.create_index(
        "idx_incidents_subject_reported",
        "incident_reports",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_incidents_reporter_subject",
        "incident_reports",
        ["reporter_agent_id", "agent_id"],
        unique=False,
    )

    op.add_column(
        "reliability_reports",
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column(
        "reliability_reports",
        "response_received",
        existing_type=sa.Boolean(),
        nullable=True,
    )

    op.drop_index("idx_reliability_reporter_agent", table_name="reliability_reports")
    op.drop_index("idx_reliability_agent_created", table_name="reliability_reports")
    op.create_index(
        "idx_reliability_subject_reported",
        "reliability_reports",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_reliability_reporter_subject",
        "reliability_reports",
        ["reporter_agent_id", "agent_id"],
        unique=False,
    )

    op.alter_column("incident_reports", "agent_id", new_column_name="subject_agent_id")
    op.alter_column("incident_reports", "created_at", new_column_name="reported_at")
    op.alter_column("reliability_reports", "agent_id", new_column_name="subject_agent_id")
    op.alter_column("reliability_reports", "created_at", new_column_name="reported_at")

    op.rename_table("incident_reports", "agent_incidents")
    op.rename_table("reliability_reports", "agent_reliability_reports")
