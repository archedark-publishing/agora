"""Proof-of-life gating for directory listings.

Adds ``listing_status`` ('pending' | 'active') and ``pending_reason`` to
``agents``. A listing is public only after demonstrating the thing is real:
a reachable agent card (URL registrations) or a clicked verification link
(email-only registrations).

Backfill is evidence-based and mechanical, never editorial: any listing with
``email_verified = true``, ``health_status = 'healthy'``, or a non-null
``last_healthy_at`` is marked active. Everything else becomes pending with
an explanatory reason; owners can activate via the retry-health-check
endpoint (URL path) or the email verification link (email-only path).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260929_0025"
down_revision = "20260928_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents",
        sa.Column(
            "listing_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column("agents", sa.Column("pending_reason", sa.Text(), nullable=True))
    op.create_index("idx_agents_listing_status", "agents", ["listing_status"])
    # Backfill: keep every listing that ever proved it exists; park the rest
    # as pending. Mechanical, based only on recorded evidence.
    op.execute(
        sa.text(
            """
            UPDATE agents
            SET listing_status = 'pending',
                pending_reason = 'Backfilled: never verified or health-checked'
            WHERE NOT (
                email_verified = true
                OR health_status = 'healthy'
                OR last_healthy_at IS NOT NULL
            )
            """
        )
    )


def downgrade():
    op.drop_index("idx_agents_listing_status", table_name="agents")
    op.drop_column("agents", "pending_reason")
    op.drop_column("agents", "listing_status")
