#!/usr/bin/env sh
set -e

echo "Starting Celery worker..."
exec celery -A app.celery_app.celery worker --loglevel=${LOG_LEVEL:-info} -Q default
