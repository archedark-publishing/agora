"""add sybil resistance metadata fields to reputation tables

Revision ID: 20260320_0014
Revises: 20260320_0013
Create Date: 2026-03-20 16:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260320_0014"
down_revision = "20260320_0013"
branch_labels = None
depends_on = None


def _recreate_reliability_scores_view() -> None:
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
          AND retracted_at IS NULL
          AND (held_until IS NULL OR held_until <= NOW())
        GROUP BY agent_id
        """
    )
    op.create_index(
        "idx_reliability_scores_agent",
        "agent_reliability_scores",
        ["agent_id"],
        unique=True,
    )


def upgrade() -> None:
    op.add_column(
        "reliability_reports",
        sa.Column("reporter_weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
    )
    op.add_column("reliability_reports", sa.Column("held_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "reliability_reports",
        sa.Column("flagged_for_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("reliability_reports", sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "incident_reports",
        sa.Column("reporter_weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
    )
    op.add_column("incident_reports", sa.Column("held_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "incident_reports",
        sa.Column("flagged_for_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("incident_reports", sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "incident_reports",
        sa.Column("disputed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("incident_reports", sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True))

    _recreate_reliability_scores_view()


def downgrade() -> None:
    op.drop_column("incident_reports", "disputed_at")
    op.drop_column("incident_reports", "disputed")
    op.drop_column("incident_reports", "retracted_at")
    op.drop_column("incident_reports", "flagged_for_review")
    op.drop_column("incident_reports", "held_until")
    op.drop_column("incident_reports", "reporter_weight")

    op.drop_column("reliability_reports", "retracted_at")
    op.drop_column("reliability_reports", "flagged_for_review")
    op.drop_column("reliability_reports", "held_until")
    op.drop_column("reliability_reports", "reporter_weight")

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
