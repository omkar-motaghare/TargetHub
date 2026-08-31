from time import sleep

from app.celery_app import celery


@celery.task(bind=True, name="app.tasks.example_long_running_task")
def example_long_running_task(self, duration: int = 10) -> str:
    """Example long-running task to demonstrate background processing.

    Args:
        duration: seconds to sleep (simulated work)

    Returns:
        A success string.
    """
    try:
        for i in range(duration):
            sleep(1)
    except Exception as exc:  # pragma: no cover - example code
        # Let Celery handle retries if configured
        raise self.retry(exc=exc, countdown=5, max_retries=3)

    return f"slept for {duration}s"
