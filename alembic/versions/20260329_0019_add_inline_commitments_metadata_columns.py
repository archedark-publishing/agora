"""add inline commitments metadata columns to agents

Revision ID: 20260329_0019
Revises: 20260329_0018
Create Date: 2026-03-29 17:52:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260329_0019"
down_revision = "20260329_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("commitments_count", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("commitments_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "commitments_summary")
    op.drop_column("agents", "commitments_count")
