"""Merge erc8004_verified and reputation phase1 schema heads

Revision ID: 20260308_0008
Revises: 20260307_0007, 20260308_0007
Create Date: 2026-03-08 23:40:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "20260308_0008"
down_revision: tuple[str, str] = ("20260307_0007", "20260308_0007")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
