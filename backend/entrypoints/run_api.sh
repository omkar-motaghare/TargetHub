#!/usr/bin/env sh
set -e

# Wait for the database, run migrations, then start Gunicorn+Uvicorn workers.
echo "Waiting for database..."
PYTHONPATH=/app python entrypoints/wait_for_db.py

echo "Running alembic migrations..."
alembic upgrade heads

echo "Starting Gunicorn..."
exec gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 "app.main:app" \
    --workers ${API_WORKERS:-2} --log-level ${LOG_LEVEL:-info}
