#!/bin/sh
# Start the mail sidecar. Run as root: postsuper and the journal need it.
cd "$(dirname "$0")"
[ -f .env ] && { set -a; . ./.env; set +a; }
exec uv run uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8025}"
