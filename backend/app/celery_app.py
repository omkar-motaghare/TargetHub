from __future__ import annotations

from celery import Celery

from .core.config import settings


def make_celery() -> Celery:
    broker = settings.broker_url or settings.redis_url
    backend = settings.redis_url
    celery = Celery("targethub", broker=broker, backend=backend)

    celery.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )

    # autodiscover tasks in app.tasks
    celery.autodiscover_tasks(["app.tasks"])

    return celery


celery = make_celery()
