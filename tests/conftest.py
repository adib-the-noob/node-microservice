import os

# Never touch a real DB from tests (set before app.config loads .env; env vars win over .env).
os.environ["DATABASE_URL"] = "sqlite://"
