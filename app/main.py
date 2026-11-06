"""Mail sidecar: a REST API that runs Postfix / OpenDKIM command-line tools.

Run with:  sudo ./run.sh
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import engine
from .models import SentMail
from .routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create sent_mail if it's missing. dkim_keys / dkim_signing already exist.
    SentMail.__table__.create(engine, checkfirst=True)
    yield


app = FastAPI(title="Mail sidecar", lifespan=lifespan)
app.include_router(router)
