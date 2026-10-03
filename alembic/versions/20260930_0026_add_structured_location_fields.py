"""add structured location fields to agents

Revision ID: 20260930_0026
Revises: 20260929_0025
Create Date: 2026-09-30

Location filter feature: structured, self-declared location fields alongside
the existing free-text `location` display column. All nullable — location is
opt-in and coarse by design (city-level; no street addresses).

- city / region: free text, max 100 chars
- country_code: ISO 3166-1 alpha-2, stored uppercase
- latitude / longitude: optional pair for radius search
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260930_0026"
down_revision = "20260929_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("region", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("country_code", sa.String(2), nullable=True))
    op.add_column("agents", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("agents", sa.Column("longitude", sa.Float(), nullable=True))
    op.create_index("idx_agents_country_code", "agents", ["country_code"])
    op.create_index("idx_agents_city", "agents", ["city"])


def downgrade() -> None:
    op.drop_index("idx_agents_city", table_name="agents")
    op.drop_index("idx_agents_country_code", table_name="agents")
    op.drop_column("agents", "longitude")
    op.drop_column("agents", "latitude")
    op.drop_column("agents", "country_code")
    op.drop_column("agents", "region")
    op.drop_column("agents", "city")
