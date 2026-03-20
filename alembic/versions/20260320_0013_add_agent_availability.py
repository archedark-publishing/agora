"""add availability metadata column to agents

Revision ID: 20260320_0013
Revises: 20260314_0012
Create Date: 2026-03-20 16:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260320_0013"
down_revision = "20260314_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("availability", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "availability")
