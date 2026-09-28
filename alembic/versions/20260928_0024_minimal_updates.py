"""Private pending email changes and case-insensitive email uniqueness.

Existing collisions must be resolved by an operator; never merge/delete listings.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0024"
down_revision = "20260928_0023"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicate = connection.execute(sa.text(
        "SELECT 1 FROM agents WHERE email IS NOT NULL GROUP BY lower(email) HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("Duplicate agent emails (case-insensitive) must be resolved before migration 20260928_0024; no listings were changed.")
    op.add_column("agents", sa.Column("pending_email", sa.String(320), nullable=True))
    op.add_column("agents", sa.Column("pending_email_nonce", sa.String(64), nullable=True))
    op.add_column("agents", sa.Column("email_generation", sa.String(64), nullable=True))
    op.create_index("uq_agents_email_lower", "agents", [sa.text("lower(email)")], unique=True)


def downgrade():
    op.drop_index("uq_agents_email_lower", table_name="agents")
    op.drop_column("agents", "email_generation")
    op.drop_column("agents", "pending_email_nonce")
    op.drop_column("agents", "pending_email")
