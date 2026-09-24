"""drop email challenge columns from agents

Revision ID: 20260924_0022
Revises: 20260924_0021
Create Date: 2026-09-24 13:45:00.000000

Agora v2: email verification moved from the domain-control challenge
(publish a token at /.well-known/agora-email-challenge.txt) to a signed
verification link emailed to the listing address. The challenge columns are
no longer written or read; drop them. email_verified stays.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260924_0022"
down_revision = "20260924_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agents", "email_challenge_expires_at")
    op.drop_column("agents", "email_challenge")


def downgrade() -> None:
    op.add_column("agents", sa.Column("email_challenge", sa.String(128), nullable=True))
    op.add_column(
        "agents",
        sa.Column("email_challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
