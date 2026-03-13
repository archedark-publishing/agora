"""add did fields to agent records

Revision ID: 20260313_0011
Revises: 20260312_0010
Create Date: 2026-03-13 12:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260313_0011"
down_revision = "20260312_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("did", sa.String(length=512), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "did_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_index("idx_agents_did", "agents", ["did"], unique=False)
    op.create_index("idx_agents_did_verified", "agents", ["did_verified"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_did_verified", table_name="agents")
    op.drop_index("idx_agents_did", table_name="agents")
    op.drop_column("agents", "did_verified")
    op.drop_column("agents", "did")
