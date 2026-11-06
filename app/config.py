"""Settings. Values come from env vars (run.sh loads them from .env)."""

import os

# Command-line tools
SENDMAIL = "/usr/sbin/sendmail"
POSTQUEUE = "/usr/sbin/postqueue"
POSTSUPER = "/usr/sbin/postsuper"  # needs root
OPENSSL = "/usr/bin/openssl"
DIG = "/usr/bin/dig"
JOURNALCTL = "/usr/bin/journalctl"
SYSTEMCTL = "/usr/bin/systemctl"

# Only these From: domains may send (comma separated). Empty = any.
ALLOWED_FROM_DOMAINS = [d.strip().lower() for d in os.environ.get("ALLOWED_FROM_DOMAINS", "").split(",") if d.strip()]

# Central MySQL DB (the one OpenDKIM reads)
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_SSL_CA = os.environ.get("DB_SSL_CA", "")  # optional: check the server cert against this CA
