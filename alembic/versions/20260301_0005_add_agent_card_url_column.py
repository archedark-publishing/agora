"""add agent_card_url column to agents

Revision ID: 20260301_0005
Revises: 20260223_0004
Create Date: 2026-03-01 13:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260301_0005"
down_revision: str | None = "20260223_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("agent_card_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "agent_card_url")
