"""In-process application metrics (Phase 7).

Not a time-series database. Values reset on process restart.
Documented limitation: local/dev observability only.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


_MAX_LATENCY_SAMPLES = 500


def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._started_at = time.time()

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latencies.clear()
            self._started_at = time.time()

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, ms: float) -> None:
        with self._lock:
            bucket = self._latencies[name]
            bucket.append(float(ms))
            if len(bucket) > _MAX_LATENCY_SAMPLES:
                del bucket[: len(bucket) - _MAX_LATENCY_SAMPLES]

    def get_counter(self, name: str) -> int:
        with self._lock:
            return int(self._counters.get(name, 0))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            latency_stats: dict[str, Any] = {}
            for name, samples in self._latencies.items():
                ordered = sorted(samples)
                n = len(ordered)
                avg = sum(ordered) / n if n else None
                latency_stats[name] = {
                    "count": n,
                    "avg_ms": None if avg is None else round(avg, 2),
                    "p50_ms": None
                    if not ordered
                    else round(_percentile(ordered, 50) or 0, 2),
                    "p95_ms": None
                    if not ordered
                    else round(_percentile(ordered, 95) or 0, 2),
                }

        def rate(num: str, den: str) -> float | None:
            d = counters.get(den, 0)
            if d <= 0:
                return None
            return round(counters.get(num, 0) / d, 6)

        return {
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "durable": False,
            "note": "In-memory metrics; reset on process restart.",
            "counters": counters,
            "latencies": latency_stats,
            "derived": {
                "request_error_rate": rate("http.requests_5xx", "http.requests_total"),
                "retrieval_empty_rate": rate(
                    "retrieval.empty", "retrieval.attempts"
                ),
                "generation_timeout_rate": rate(
                    "generation.timeout", "generation.attempts"
                ),
                "judge_timeout_rate": rate("judge.timeout", "judge.attempts"),
                "judge_malformed_rate": rate(
                    "judge.malformed", "judge.attempts"
                ),
                "retrieval_miss_rate": rate(
                    "diagnosis.code.RETRIEVAL_MISS", "diagnosis.total"
                ),
            },
        }


_REGISTRY = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _REGISTRY
