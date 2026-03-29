"""add oatr_issuer_id column to agents

Revision ID: 20260329_0018
Revises: 20260327_0017
Create Date: 2026-03-29 17:35:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260329_0018"
down_revision = "20260327_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("oatr_issuer_id", sa.String(length=255), nullable=True))
    op.create_index("idx_agents_oatr_issuer_id", "agents", ["oatr_issuer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_oatr_issuer_id", table_name="agents")
    op.drop_column("agents", "oatr_issuer_id")
