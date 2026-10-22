import os
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(os.getenv("TARGETHUB_LOG_DIR", "app/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.configure(extra={"request_id": "-"})

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _default_enqueue() -> bool:
    # Pytest and similarly constrained environments may forbid creating
    # multiprocessing semaphores used by Loguru queue mode.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return True


def _add_handler_with_fallback(*args, enqueue: bool, **kwargs) -> None:
    try:
        logger.add(*args, enqueue=enqueue, **kwargs)
    except (PermissionError, OSError):
        if enqueue:
            logger.add(*args, enqueue=False, **kwargs)
            return
        raise


LOG_ENQUEUE = _env_bool("TARGETHUB_LOG_ENQUEUE", _default_enqueue())
LOG_JSON = os.getenv("TARGETHUB_LOG_FORMAT", "text").strip().lower() == "json"
LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[request_id]} | "
    "{name}:{function}:{line} | {message}"
)

# diagnose stays off: it prints local variable values into tracebacks, which can leak secrets.
if LOG_JSON:
    _add_handler_with_fallback(
        sys.stdout, level="INFO", enqueue=LOG_ENQUEUE, serialize=True, backtrace=False, diagnose=False
    )
else:
    _add_handler_with_fallback(
        sys.stdout,
        level="INFO",
        colorize=True,
        enqueue=LOG_ENQUEUE,
        backtrace=True,
        diagnose=False,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<magenta>{extra[request_id]}</magenta> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>",
    )

_add_handler_with_fallback(
    LOG_DIR / "targethub.log",
    rotation="10 MB",
    retention="30 days",
    compression="zip",
    enqueue=LOG_ENQUEUE,
    level="DEBUG",
    backtrace=True,
    diagnose=False,
    format=LOG_FORMAT,
)

__all__ = ["logger"]
