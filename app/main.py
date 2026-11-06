"""Mail sidecar: a REST API that runs Postfix / OpenDKIM command-line tools.

Run with:  docker compose up -d   (or sudo ./run.sh)
Tables are created/updated by Alembic (`alembic upgrade head`) before the app starts.
"""

from fastapi import FastAPI

from .routes import router

app = FastAPI(title="Mail sidecar")
app.include_router(router)
