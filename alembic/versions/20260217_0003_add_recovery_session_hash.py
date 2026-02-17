"""add recovery session hash

Revision ID: 20260217_0003
Revises: 20260217_0002
Create Date: 2026-02-17 00:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260217_0003"
down_revision = "20260217_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("recovery_session_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "recovery_session_hash")
