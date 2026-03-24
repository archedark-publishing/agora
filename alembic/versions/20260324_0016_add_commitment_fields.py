"""add commitments url and verification status to agents

Revision ID: 20260324_0016
Revises: 20260324_0015
Create Date: 2026-03-24 12:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260324_0016"
down_revision = "20260324_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("commitments_url", sa.String(length=2048), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "commitment_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "commitment_verified")
    op.drop_column("agents", "commitments_url")
