"""SQLAlchemy engine and session for the central MariaDB DB."""

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker

from . import config

engine = create_engine(
    make_url(config.DATABASE_URL).set(drivername="mariadb+pymysql"),  # paste mariadb://... as-is
    connect_args={"connect_timeout": 10},
    pool_pre_ping=True,  # drop connections the server closed while idle
    pool_recycle=3600,
)
SessionLocal = sessionmaker(engine)


def get_db():
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
