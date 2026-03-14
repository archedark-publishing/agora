"""add systematic_under_caution incident category

Revision ID: 20260314_0012
Revises: 20260313_0011
Create Date: 2026-03-14 08:20:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260314_0012"
down_revision = "20260313_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_incident_category", "incident_reports", type_="check")
    op.create_check_constraint(
        "ck_incident_category",
        "incident_reports",
        (
            "category IN ('refusal_to_comply', 'deceptive_output', 'data_handling_concern', "
            "'capability_misrepresentation', 'systematic_under_caution', "
            "'positive_exceptional_service', 'other')"
        ),
    )


def downgrade() -> None:
    op.drop_constraint("ck_incident_category", "incident_reports", type_="check")
    op.create_check_constraint(
        "ck_incident_category",
        "incident_reports",
        (
            "category IN ('refusal_to_comply', 'deceptive_output', 'data_handling_concern', "
            "'capability_misrepresentation', 'positive_exceptional_service', 'other')"
        ),
    )
