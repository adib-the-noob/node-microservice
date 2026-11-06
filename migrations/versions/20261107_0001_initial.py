"""domains, dns_records, sent_mail

Revision ID: 0001
Revises:
Create Date: 2026-11-07

These tables were first made by the app at startup (create_all), so each one is
created only if it's missing. That way existing DBs upgrade cleanly.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "domains" not in existing:
        op.create_table(
            "domains",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, unique=True),
            sa.Column("selector", sa.String(63), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )
    if "dns_records" not in existing:
        op.create_table(
            "dns_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(10), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.UniqueConstraint("domain_id", "type", "name"),
        )
    if "sent_mail" not in existing:
        op.create_table(
            "sent_mail",
            sa.Column("message_id", sa.String(255), primary_key=True),
            sa.Column("node", sa.String(255), nullable=False),
            sa.Column("sender", sa.String(255), nullable=False),
            sa.Column("recipients", sa.Text(), nullable=False),
            sa.Column("subject", sa.String(998), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("dns_records")
    op.drop_table("domains")
    op.drop_table("sent_mail")
