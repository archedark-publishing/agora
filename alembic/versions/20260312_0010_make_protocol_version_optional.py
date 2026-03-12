"""make protocol_version optional and filter-friendly

Revision ID: 20260312_0010
Revises: 20260311_0009
Create Date: 2026-03-12 00:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260312_0010"
down_revision = "20260311_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("valid_protocol_version", "agents", type_="check")

    op.alter_column(
        "agents",
        "protocol_version",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
        nullable=True,
        existing_server_default=sa.text("'0.3.0'"),
        server_default=None,
    )

    op.execute("UPDATE agents SET protocol_version = NULL")
    op.create_index("idx_agents_protocol_version", "agents", ["protocol_version"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_protocol_version", table_name="agents")

    op.execute("UPDATE agents SET protocol_version = '0.3.0' WHERE protocol_version IS NULL")

    op.alter_column(
        "agents",
        "protocol_version",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("'0.3.0'"),
    )

    op.create_check_constraint(
        "valid_protocol_version",
        "agents",
        r"protocol_version ~ '^\\d+\\.\\d+\\.\\d+$'",
    )
