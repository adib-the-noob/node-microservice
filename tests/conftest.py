import os

# Tests never depend on the developer's .env (set before app.config loads it; env vars win over .env).
os.environ["DATABASE_URL"] = "sqlite://"  # never touch a real DB
os.environ["APP_ENV"] = "production"
