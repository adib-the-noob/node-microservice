"""SQLAlchemy engine and session for the central MySQL DB."""

import ssl

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from . import config

tls = ssl.create_default_context(cafile=config.DB_SSL_CA or None)
if not config.DB_SSL_CA:  # encrypt, but don't check the cert (like mysql --ssl-mode=REQUIRED)
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE

engine = create_engine(
    URL.create("mysql+pymysql", username=config.DB_USER, password=config.DB_PASSWORD,
               host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME),
    connect_args={"ssl": tls, "connect_timeout": 10},
    pool_pre_ping=True,  # drop connections the server closed while idle
    pool_recycle=3600,
)
SessionLocal = sessionmaker(engine)


def get_db():
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
