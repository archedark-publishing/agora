"""add minimal directory fields to agents

Revision ID: 20260924_0021
Revises: 20260401_0020
Create Date: 2026-09-24 12:00:00.000000

Agora v2: the registry becomes a minimal agent directory. Listings center on
an email contact address and a self-reported response SLA instead of the
A2A agent-card / DID / ERC-8004 machinery. These columns back that model:

- email / response_sla: the core contact listing
- email_verified: whether domain control was proven via the challenge flow
- email_challenge / email_challenge_expires_at: pending verification state
- directory_slug: unique human-friendly slug for the machine-readable feed

The registered `url` becomes nullable: email-only listings have no website
or agent endpoint to probe.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260924_0021"
down_revision = "20260401_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("agents", sa.Column("response_sla", sa.String(255), nullable=True))
    op.add_column(
        "agents",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("agents", sa.Column("email_challenge", sa.String(128), nullable=True))
    op.add_column(
        "agents",
        sa.Column("email_challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("agents", sa.Column("directory_slug", sa.String(255), nullable=True))
    # Email-only listings have no URL to probe; Postgres unique constraints
    # permit multiple NULLs, so existing uniqueness semantics are preserved.
    op.alter_column("agents", "url", existing_type=sa.String(2048), nullable=True)
    op.create_index("idx_agents_email", "agents", ["email"])
    op.create_unique_constraint("uq_agents_directory_slug", "agents", ["directory_slug"])


def downgrade() -> None:
    op.drop_constraint("uq_agents_directory_slug", "agents", type_="unique")
    op.drop_index("idx_agents_email", table_name="agents")
    op.alter_column("agents", "url", existing_type=sa.String(2048), nullable=False)
    op.drop_column("agents", "directory_slug")
    op.drop_column("agents", "email_challenge_expires_at")
    op.drop_column("agents", "email_challenge")
    op.drop_column("agents", "email_verified")
    op.drop_column("agents", "response_sla")
    op.drop_column("agents", "email")
