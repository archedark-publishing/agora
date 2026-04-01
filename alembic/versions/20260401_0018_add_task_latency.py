"""add task_latency column to agents

Revision ID: 20260401_0018
Revises: 20260327_0017
Create Date: 2026-04-01 11:20:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260401_0018"
down_revision = "20260327_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("task_latency", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "task_latency")
