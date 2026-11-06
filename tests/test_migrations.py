from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.models import Base, include_object


def _alembic(conn) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["connection"] = conn
    return cfg


def test_migrations_match_models_and_skip_prime_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # OpenDKIM's tables already exist (with a row); migrations must leave them alone
        conn.execute(text("CREATE TABLE dkim_keys (key_id VARCHAR(255) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO dkim_keys VALUES ('s1._domainkey.a.com')"))
        command.upgrade(_alembic(conn), "head")

        assert {"domains", "dns_records", "sent_mail", "alembic_version"} <= set(inspect(conn).get_table_names())
        assert "dkim_signing" not in inspect(conn).get_table_names()
        assert conn.execute(text("SELECT count(*) FROM dkim_keys")).scalar() == 1

        # models and migrations agree: autogenerate would produce nothing
        ctx = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []

        command.downgrade(_alembic(conn), "base")
        assert "domains" not in inspect(conn).get_table_names()
        assert "dkim_keys" in inspect(conn).get_table_names()


def test_upgrade_is_safe_when_tables_already_exist():
    """DBs where the app already made the tables with create_all."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        command.upgrade(_alembic(conn), "head")
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
