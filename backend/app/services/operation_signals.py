"""In-process wakeups for Agent operation queueing and completion.

The database is the source of truth for Agent operations, so every waiter
still re-checks it periodically. These signals only shorten latency when the
producer (an API request queueing work, or an Agent reporting completion)
happens to run in the same worker process as the waiter. With several
Gunicorn workers the fallback interval bounds the extra latency.

Producers usually run in a threadpool thread while waiters run on the event
loop, so ``notify`` hands the wakeup to the waiter's loop thread-safely.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict

FALLBACK_INTERVAL_SECONDS = 0.25


class _SignalHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = defaultdict(set)

    def subscribe(self, key: str) -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
        entry = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._waiters[key].add(entry)
        return entry

    def unsubscribe(self, key: str, entry: tuple[asyncio.AbstractEventLoop, asyncio.Event]) -> None:
        with self._lock:
            waiters = self._waiters.get(key)
            if waiters is None:
                return
            waiters.discard(entry)
            if not waiters:
                self._waiters.pop(key, None)

    def notify(self, key: str) -> None:
        with self._lock:
            waiters = list(self._waiters.get(key, ()))
        for loop, event in waiters:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # loop already closed
                continue

    def listen(self, key: str) -> _Listener:
        """Subscribe before checking the database so no wakeup is lost in between."""
        return _Listener(self, key)


class _Listener:
    def __init__(self, hub: _SignalHub, key: str) -> None:
        self._hub = hub
        self._key = key
        self._entry: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None

    async def __aenter__(self) -> _Listener:
        self._entry = self._hub.subscribe(self._key)
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._entry is not None:
            self._hub.unsubscribe(self._key, self._entry)

    async def wait(self, timeout: float) -> bool:
        """Wait for a notification or ``timeout``; True when notified. Resets the flag."""
        assert self._entry is not None
        event = self._entry[1]
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, timeout))
            notified = True
        except TimeoutError:
            notified = False
        event.clear()
        return notified


signals = _SignalHub()


def agent_key(agent_id: str) -> str:
    return f"agent:{agent_id}"


def operation_key(operation_id: str) -> str:
    return f"op:{operation_id}"
