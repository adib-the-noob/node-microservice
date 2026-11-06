FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Migrate first (one node at a time, see migrations/env.py), then serve.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8025}\""]
