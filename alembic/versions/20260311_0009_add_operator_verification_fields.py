"""add operator verification fields to agents

Revision ID: 20260311_0009
Revises: 20260308_0008
Create Date: 2026-03-11 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260311_0009"
down_revision = "20260308_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("operator", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agents", sa.Column("operator_challenge_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "agents",
        sa.Column("operator_challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("operator_challenge_created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "operator_challenge_created_at")
    op.drop_column("agents", "operator_challenge_expires_at")
    op.drop_column("agents", "operator_challenge_hash")
    op.drop_column("agents", "operator")
