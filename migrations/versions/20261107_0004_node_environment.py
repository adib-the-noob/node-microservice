"""nodes.environment (production / local)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows are mail servers, so they get "production".
    op.add_column("nodes", sa.Column("environment", sa.String(20), nullable=False, server_default="production"))


def downgrade() -> None:
    op.drop_column("nodes", "environment")
