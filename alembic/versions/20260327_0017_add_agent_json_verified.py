"""add agent_json_verified flag to agents

Revision ID: 20260327_0017
Revises: 20260324_0016
Create Date: 2026-03-27 11:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260327_0017"
down_revision = "20260324_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "agent_json_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("idx_agents_agent_json_verified", "agents", ["agent_json_verified"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_agent_json_verified", table_name="agents")
    op.drop_column("agents", "agent_json_verified")
