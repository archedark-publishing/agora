"""add erc8004_verified flag to agents

Revision ID: 20260308_0007
Revises: 20260303_0006
Create Date: 2026-03-08 19:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260308_0007"
down_revision = "20260303_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("erc8004_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )



def downgrade() -> None:
    op.drop_column("agents", "erc8004_verified")
