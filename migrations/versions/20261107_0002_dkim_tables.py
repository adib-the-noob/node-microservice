"""dkim_keys, dkim_signing (OpenDKIM's tables)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07

Creates each table only if it's missing (a fresh DB). Existing tables are left
exactly as they are, and downgrade never drops them: they hold the live keys.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MARIADB = {"mariadb_engine": "InnoDB", "mariadb_charset": "utf8mb4"}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "dkim_keys" not in existing:
        op.create_table(
            "dkim_keys",
            sa.Column("key_id", sa.String(320), primary_key=True),  # s1._domainkey.unifyed.tech
            sa.Column("domain", sa.String(253), nullable=False),     # unifyed.tech
            sa.Column("selector", sa.String(63), nullable=False),    # s1
            sa.Column("private_key", sa.Text(), nullable=False),     # full PEM
            sa.Column("public_key", sa.Text(), nullable=False),      # PEM public key
            sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.UniqueConstraint("domain", "selector", name="uq_domain_selector"),
            **MARIADB,
        )
    if "dkim_signing" not in existing:
        op.create_table(
            "dkim_signing",
            sa.Column("author", sa.String(255), primary_key=True),  # unifyed.tech, @unifyed.tech, *@unifyed.tech
            sa.Column("key_id", sa.String(320), nullable=False),
            sa.ForeignKeyConstraint(["key_id"], ["dkim_keys.key_id"], name="fk_signing_key", ondelete="CASCADE"),
            **MARIADB,
        )
        op.create_index("idx_key_id", "dkim_signing", ["key_id"])


def downgrade() -> None:
    pass  # never drop OpenDKIM's tables
