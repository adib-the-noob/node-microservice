"""SQLAlchemy engine and session for the central MySQL DB."""

import ssl

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker

from . import config

url = make_url(config.DATABASE_URL)
connect_args = {}
if url.get_backend_name() == "mysql":
    url = url.set(drivername="mysql+pymysql")  # plain mysql:// would need the MySQLdb C driver
    tls = ssl.create_default_context(cafile=config.DB_SSL_CA or None)
    if not config.DB_SSL_CA:  # encrypt, but don't check the cert (like mysql --ssl-mode=REQUIRED)
        tls.check_hostname = False
        tls.verify_mode = ssl.CERT_NONE
    connect_args = {"ssl": tls, "connect_timeout": 10}

engine = create_engine(
    url,
    connect_args=connect_args,
    pool_pre_ping=True,  # drop connections the server closed while idle
    pool_recycle=3600,
)
SessionLocal = sessionmaker(engine)


def get_db():
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
