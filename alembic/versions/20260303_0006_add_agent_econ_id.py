"""add optional econ_id to agents

Revision ID: 20260303_0006
Revises: 20260301_0005
Create Date: 2026-03-03 21:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_0006"
down_revision = "20260301_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("econ_id", sa.String(length=255), nullable=True))
    op.create_index("idx_agents_econ_id", "agents", ["econ_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_econ_id", table_name="agents")
    op.drop_column("agents", "econ_id")
