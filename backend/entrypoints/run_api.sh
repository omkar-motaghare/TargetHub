#!/usr/bin/env sh
set -e

# Run migrations then start the API with Gunicorn+Uvicorn workers.
echo "Running alembic migrations..."
alembic upgrade heads

echo "Starting Gunicorn..."
exec gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 "app.main:app" \
    --workers ${API_WORKERS:-2} --log-level ${LOG_LEVEL:-info}
