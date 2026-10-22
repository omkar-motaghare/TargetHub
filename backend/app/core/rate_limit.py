import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class FailureLimiter:
    """Sliding-window counter of failed attempts per key (process-local)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        if not attempts:
            self._failures.pop(key, None)
        return attempts

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until another attempt is allowed; 0 when the key is not blocked."""
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(key, window, now)
            if len(attempts) < limit:
                return 0
            return max(1, int(window - (now - attempts[0])) + 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


auth_limiter = FailureLimiter()
IP_LIMIT_MULTIPLIER = 4


def auth_keys(client_ip: str | None, username: str) -> tuple[str, str]:
    ip = client_ip or "unknown"
    return f"user:{ip}:{username.strip().lower()}", f"ip:{ip}"


def enforce_auth_limit(client_ip: str | None, username: str, max_failures: int, window_seconds: int) -> None:
    user_key, ip_key = auth_keys(client_ip, username)
    wait = max(
        auth_limiter.retry_after(user_key, max_failures, window_seconds),
        auth_limiter.retry_after(ip_key, max_failures * IP_LIMIT_MULTIPLIER, window_seconds),
    )
    if wait:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts; try again later",
            headers={"Retry-After": str(wait)},
        )


def record_auth_failure(client_ip: str | None, username: str) -> None:
    user_key, ip_key = auth_keys(client_ip, username)
    auth_limiter.record_failure(user_key)
    auth_limiter.record_failure(ip_key)


def record_auth_success(client_ip: str | None, username: str) -> None:
    auth_limiter.reset(auth_keys(client_ip, username)[0])
