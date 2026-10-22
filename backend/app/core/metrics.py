from __future__ import annotations

import threading
from collections import defaultdict


class MetricsRegistry:
    """Minimal thread-safe in-process metrics for the prototype.

    Exposes counters and gauges and renders them in Prometheus text format.
    This avoids an external dependency while providing real observability.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None):
        items = tuple(sorted((labels or {}).items()))
        return name, items

    def inc(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    @staticmethod
    def _format_labels(items: tuple[tuple[str, str], ...]) -> str:
        if not items:
            return ""
        inner = ",".join(f'{k}="{v}"' for k, v in items)
        return "{" + inner + "}"

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)

        emitted_help: set[str] = set()
        for (name, items), value in sorted(counters.items()):
            if name not in emitted_help:
                lines.append(f"# TYPE {name} counter")
                emitted_help.add(name)
            lines.append(f"{name}{self._format_labels(items)} {value}")
        for (name, items), value in sorted(gauges.items()):
            if name not in emitted_help:
                lines.append(f"# TYPE {name} gauge")
                emitted_help.add(name)
            lines.append(f"{name}{self._format_labels(items)} {value}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
