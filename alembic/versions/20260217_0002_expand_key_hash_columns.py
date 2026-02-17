"""expand key hash columns for argon2

Revision ID: 20260217_0002
Revises: 20260216_0001
Create Date: 2026-02-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260217_0002"
down_revision = "20260216_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agents",
        "owner_key_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "agents",
        "recovery_challenge_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "agents",
        "recovery_challenge_hash",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
    op.alter_column(
        "agents",
        "owner_key_hash",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
