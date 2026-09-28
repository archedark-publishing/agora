"""add optional location column to agents

Revision ID: 20260928_0023
Revises: 20260924_0022
Create Date: 2026-09-28 12:30:00.000000

Agora v2 minimal directory: listings can self-declare a free-text location
(e.g. "Philadelphia, PA" or "Remote"). Purely optional and informational —
no geocoding, no proximity search. It lets local-service agents (the
"business front door" use case) say where they operate so browsers don't
message a plumber only to learn he's on another continent.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260928_0023"
down_revision = "20260924_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("location", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "location")
