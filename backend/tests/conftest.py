import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
backend_path = str(BACKEND_ROOT)

if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Tests drive maintenance explicitly via run_maintenance().
os.environ.setdefault("SCHEDULER_ENABLED", "false")
# Keep the suite fast; production uses the 600k default.
os.environ.setdefault("PASSWORD_HASH_ITERATIONS", "20000")


@pytest.fixture(autouse=True)
def reset_auth_limiter():
    from app.core.rate_limit import auth_limiter

    auth_limiter.clear()
    yield
    auth_limiter.clear()
