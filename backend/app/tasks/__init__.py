"""Celery task package for TargetHub.

Place background task modules here. Celery will autodiscover tasks
from this package.
"""

from .sample_tasks import example_long_running_task  # re-export for convenience

__all__ = ["example_long_running_task"]
