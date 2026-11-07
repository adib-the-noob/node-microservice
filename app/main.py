"""Mail sidecar: a REST API that runs Postfix / OpenDKIM command-line tools.

Run with:  docker compose up -d   (or sudo ./run.sh)
Tables are created/updated by Alembic (`alembic upgrade head`) before the app starts.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import node
from .db import SessionLocal
from .routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        node.register(db)  # upsert this node in `nodes`, keyed by IPv4
    yield


app = FastAPI(title="Mail sidecar", lifespan=lifespan)
app.include_router(router)
