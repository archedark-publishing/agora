"""create agents table

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260216_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column(
            "protocol_version",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'0.3.0'"),
        ),
        sa.Column("agent_card", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("capabilities", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("input_modes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("output_modes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("owner_key_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "health_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_challenge_hash", sa.String(length=64), nullable=True),
        sa.Column("recovery_challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_challenge_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            r"protocol_version ~ '^\d+\.\d+\.\d+$'",
            name="valid_protocol_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("idx_agents_skills", "agents", ["skills"], unique=False, postgresql_using="gin")
    op.create_index(
        "idx_agents_capabilities",
        "agents",
        ["capabilities"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("idx_agents_tags", "agents", ["tags"], unique=False, postgresql_using="gin")
    op.create_index("idx_agents_health", "agents", ["health_status"], unique=False)
    op.create_index("idx_agents_name", "agents", ["name"], unique=False)
    op.create_index("idx_agents_last_healthy_at", "agents", ["last_healthy_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agents_last_healthy_at", table_name="agents")
    op.drop_index("idx_agents_name", table_name="agents")
    op.drop_index("idx_agents_health", table_name="agents")
    op.drop_index("idx_agents_tags", table_name="agents")
    op.drop_index("idx_agents_capabilities", table_name="agents")
    op.drop_index("idx_agents_skills", table_name="agents")
    op.drop_table("agents")
