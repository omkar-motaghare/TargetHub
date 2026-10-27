"""Block until the configured database accepts connections (used before migrations)."""

import os
import sys
import time

from sqlalchemy import create_engine, text

from app.core.config import settings


def main() -> int:
    timeout = float(os.environ.get("DB_WAIT_TIMEOUT", "60"))
    deadline = time.monotonic() + timeout
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"database ready after {attempt} attempt(s)", flush=True)
            return 0
        except Exception as exc:
            if time.monotonic() >= deadline:
                print(f"database not reachable after {timeout:.0f}s: {exc.__class__.__name__}", file=sys.stderr)
                return 1
            time.sleep(1.5)


if __name__ == "__main__":
    sys.exit(main())
