"""Settings, from env vars. A .env file in the project root is loaded too
(for the app and for alembic); real env vars win over it."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# In Docker the tools are the host's: commands run in the host's namespaces via nsenter
# (needs `pid: host` + `privileged: true`, see docker-compose.yml).
HOST_PREFIX = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"] if os.environ.get("RUN_ON_HOST") else []

# Command-line tools (paths on the host)
SENDMAIL = "/usr/sbin/sendmail"
POSTQUEUE = "/usr/sbin/postqueue"
POSTSUPER = "/usr/sbin/postsuper"  # needs root
OPENSSL = "/usr/bin/openssl"
DIG = "/usr/bin/dig"
JOURNALCTL = "/usr/bin/journalctl"
SYSTEMCTL = "/usr/bin/systemctl"
IP = "/usr/sbin/ip"

# Where this copy runs: "production" (a mail server) or "local" (a developer PC).
# Stored on the node's row in the nodes table.
APP_ENV = os.environ.get("APP_ENV", "production").strip().lower()
if APP_ENV not in ("production", "local"):
    raise RuntimeError(f"APP_ENV must be 'production' or 'local', not {APP_ENV!r}")

# DNS records every new domain must publish (besides its DKIM key)
SPF_RECORD = os.environ.get("SPF_RECORD", "v=spf1 include:spf.metrovps.art ~all")
DMARC_RECORD = os.environ.get("DMARC_RECORD", "v=DMARC1; p=none; adkim=r; aspf=r")

# Central MariaDB DB (the one OpenDKIM reads)
# e.g. mariadb+pymysql://user:password@host:3306/dbname (URL-encode special characters in the password)
DATABASE_URL = os.environ["DATABASE_URL"]
