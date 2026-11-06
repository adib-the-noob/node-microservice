"""Alembic environment.

The DB is DATABASE_URL from .env (loaded by app/config.py, through app.db).
Which tables migrations may touch: see include_object in app/models.py."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from app.db import engine
from app.models import Base, include_object

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def run(conn):
    if conn.dialect.name == "mysql":
        # Every node runs migrations at startup; only one at a time.
        conn.execute(text("SELECT GET_LOCK('alembic_migrate', 300)"))
        conn.commit()
    context.configure(connection=conn, target_metadata=Base.metadata,
                      include_object=include_object, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


# Tests pass their own connection; otherwise use the app's engine.
if (conn := context.config.attributes.get("connection")) is not None:
    run(conn)
else:
    with engine.connect() as conn:
        run(conn)
