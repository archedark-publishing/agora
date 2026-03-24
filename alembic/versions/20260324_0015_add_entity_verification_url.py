"""add entity verification url to agent records

Revision ID: 20260324_0015
Revises: 20260320_0014
Create Date: 2026-03-24 12:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260324_0015"
down_revision = "20260320_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("entity_verification_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "entity_verification_url")
